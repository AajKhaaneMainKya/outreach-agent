"""Isolated Hermes runtime: bounded research and draft tools, never approval or sending."""
import contextlib
import inspect
import json
import os
import sys
import uuid
import types
import re
from pathlib import Path

project = Path(os.environ.get('GTM_PROJECT', Path(__file__).resolve().parents[1]))
source = Path(os.environ.get('HERMES_SOURCE', '~/.hermes/hermes-agent')).expanduser()
# A dedicated profile prevents inheriting personal MCP servers, plugins, hooks or memory.
os.environ['HERMES_HOME'] = str(project / 'data' / 'hermes')
# Subscription admission/reasoning can pause between SSE events. Keep a bounded
# allowance rather than Hermes' 12-second small-context default.
os.environ['HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS'] = '120'
sys.path.insert(0, str(source))

def main():
    with contextlib.redirect_stdout(sys.stderr):
        from run_agent import AIAgent
        from hermes_cli.runtime_provider import resolve_runtime_provider
    required = {'enabled_toolsets', 'skip_context_files', 'skip_memory', 'ephemeral_system_prompt'}
    if not required.issubset(inspect.signature(AIAgent).parameters):
        raise RuntimeError('Unsupported Hermes library API; use the tested version from README')
    if '--check' in sys.argv:
        print('Hermes library contract OK; no model request or authentication attempted')
        return
    payload = json.load(sys.stdin)
    model = os.environ['HERMES_MODEL']
    is_playbook = payload.get('workflow') == 'playbook'
    discovery=payload.get('task')=='discover'
    session=None;maps_names=[]
    enabled=['delegation']
    if is_playbook and (payload.get('candidate_id') or discovery):
        sys.path.insert(0,str(project))
        from gtm.research_tools import ResearchSession,DiscoverySession,message
        from tools.registry import registry
        from tools.mcp_tool import register_mcp_servers
        session=DiscoverySession(payload['prospect']['campaign'],payload['run_id']) if discovery else ResearchSession(payload['prospect']['research'],payload['prospect']['campaign'],payload['candidate_id'])
        session.register(registry)
        use_web=payload['prospect']['campaign'].get('source')!='places'
        server='continere_search' if use_web else 'continere_maps'
        maps_names=register_mcp_servers({server:{'command':sys.executable,'args':[str(project/('scripts/search_mcp.py' if use_web else 'scripts/maps_mcp.py'))],'env':{'GTM_SEARCH_CAMPAIGN':json.dumps(payload['prospect']['campaign']),'GTM_MAPS_CAMPAIGN':json.dumps(payload['prospect']['campaign'])},'timeout':35}})
        enabled+=(['continere_mission'] if discovery else ['continere_research','continere_workspace'])+['continere_board','mcp-'+server]
        if session:
            for tool_name in maps_names:
                entry=registry.get_entry(tool_name);original_maps=entry.handler
                def captured(args,_original=original_maps,**kw):
                    if session.root_task_id and kw.get('task_id')!=session.root_task_id and session.task_roles.get(kw.get('task_id')) not in ('researcher','discovery'):return json.dumps({'error':'Search is available only to the researcher/discovery roles; ask them on the board.'})
                    result=_original(args,**kw)
                    if discovery:session.capture(result)
                    session.note('research','Search tool returned source results or an explicit access limitation.');return result
                registry.register(name=entry.name,toolset=entry.toolset,schema=entry.schema,handler=captured,check_fn=entry.check_fn,override=True)
        if '--check-agentic' in sys.argv:
            from model_tools import get_tool_definitions
            schemas=get_tool_definitions(enabled_toolsets=enabled,quiet_mode=True)
            print(json.dumps({'tools':[t['function']['name'] for t in schemas],'maps_tools':maps_names,'maps_key_configured':bool(os.environ.get('GOOGLE_PLACES_API_KEY')),'maps_probe':registry.dispatch(maps_names[0],{'search_term':'massage spa'}) if maps_names and not os.environ.get('GOOGLE_PLACES_API_KEY') else 'not invoked'}));return
    with contextlib.redirect_stdout(sys.stderr):
        runtime = resolve_runtime_provider(requested='openai-codex', target_model=model)
        if runtime.get('provider') != 'openai-codex':
            raise RuntimeError('Subscription provider required; no paid API fallback')
        agent = AIAgent(model=model, provider=runtime['provider'], api_mode=runtime['api_mode'],
            api_key=runtime.get('api_key'), base_url=runtime.get('base_url'), enabled_toolsets=enabled,
            max_iterations=24 if session else 14, quiet_mode=True, save_trajectories=False, skip_context_files=True, skip_memory=True,
            ephemeral_system_prompt=(project / ('prompts/playbook-discovery.md' if discovery else 'prompts/playbook-orchestrator.md' if is_playbook else 'prompts/orchestrator.md')).read_text())
        names = {t['function']['name'] for t in agent.tools}
        expected={'delegate_task'}|(({'continere_select_prospect','continere_message_board','continere_read_board',*maps_names} if discovery else {'continere_apollo_contacts','continere_search_missing_evidence','continere_read_search_source','continere_get_evidence','continere_read_business_page','continere_note_progress','continere_save_findings','continere_message_board','continere_read_board',*maps_names}) if session else set())
        if names != expected:
            raise RuntimeError('Unexpected agent capabilities; refusing to run')
        if session:
            session.root_task_id=uuid.uuid4().hex
            import tools.delegate_tool as dt
            build_child=dt._build_child_agent
            session.completed_roles=set()
            def role_for(goal):
                m=re.match(r'^\[(researcher|qualifier|writer|qa|discovery|review_search|qualification_search|contact_search)\]',goal or '',re.I)
                if not m:raise ValueError('Start specialist goals with [researcher], [qualifier], [writer] or [qa]')
                return m.group(1).lower()
            def scoped_child(*args,**kwargs):
                bound=inspect.signature(build_child).bind(*args,**kwargs);role=role_for(bound.arguments['goal'])
                bound.arguments['role']='leaf'
                child=build_child(*bound.args,**bound.kwargs)
                sid=child._subagent_id;session.task_roles[sid]=role
                allowed={'continere_get_evidence','continere_read_board','continere_message_board','continere_note_progress'}
                if role=='researcher':allowed|={'continere_read_business_page','continere_search_missing_evidence','continere_read_search_source',*maps_names}
                if role in ('review_search','qualification_search','contact_search'):allowed|={'continere_search_missing_evidence','continere_read_search_source'}
                if role in ('researcher','contact_search'):allowed|={'continere_apollo_contacts'}
                if role=='discovery':allowed|=set(maps_names)
                child.tools=[t for t in child.tools if t['function']['name'] in allowed]
                instruction=(project/('prompts/playbook-'+role+'.md'))
                if instruction.exists():child.ephemeral_system_prompt=instruction.read_text()
                return child
            dt._build_child_agent=scoped_child
            def dispatch(self,args):
                if args.get('action') not in (None,'spawn'):return json.dumps({'error':'Use bounded synchronous specialist assignments for this mission'})
                tasks=args.get('tasks') or [{'goal':args.get('goal'),'context':args.get('context')}]
                try:
                    for task in tasks:
                        role=role_for(task.get('goal'));task['role']='leaf'
                        task['_requests']=[m for m in getattr(session,'pending_messages',{}).values() if m['recipient']==role]
                        from gtm.research_tools import board_rows,organization_updates
                        from gtm.db import connect
                        with connect() as board_db:exchanges=[m for m in board_rows(board_db,getattr(session,'cid',None),getattr(session,'run_id',None)) if m.get('mission_id')==session.root_task_id][-30:]
                        instructions=project/('prompts/playbook-'+role+'.md')
                        task['context']=json.dumps({'trusted_specialist_instructions':instructions.read_text() if instructions.exists() else 'Read-only discovery; no approval/contact','authoritative_policy':payload['authoritative_policy'],'assignment_context_untrusted':task.get('context',''),'shared_agent_exchanges':exchanges,'questions_to_answer':task['_requests'],'required_output':'Concise source-backed findings, questions and evidence IDs. Unknown facts remain null. No private reasoning or alternative outbound copy.'})
                        message(session,'orchestrator',role,'assignment',str(task['goal'])[:2000])
                    combined=[];errors=[]
                    for offset in range(0,len(tasks)):
                        current=tasks[offset]
                        role=role_for(current['goal'])
                        current['_reply_receipts']=list(getattr(session,'reply_readers',{}).get(role,[]))
                        current['_requests']=[m for m in getattr(session,'pending_messages',{}).values() if m['recipient']==role]
                        with connect() as board_db:latest=[m for m in board_rows(board_db,getattr(session,'cid',None),getattr(session,'run_id',None)) if m.get('mission_id')==session.root_task_id][-40:]
                        child_context=json.loads(current['context']);child_context['shared_agent_exchanges']=latest;child_context['questions_to_answer']=current['_requests'];child_context['answers_to_consume']=current['_reply_receipts'];child_context['other_prospect_team_updates']=organization_updates(session);child_context['team_scope_warning']='Other teams investigate different businesses. Share coordination findings; never cite their evidence as facts about this prospect.';current['context']=json.dumps(child_context)
                        part=json.loads(dt.delegate_task(tasks=tasks[offset:offset+1],max_iterations=5,role='leaf',background=False,parent_agent=self))
                        if part.get('error'):errors.append(str(part['error']))
                        for entry in part.get('results',[]):
                            entry['task_index']=entry.get('task_index',0)+offset;combined.append(entry)
                            if isinstance(entry.get('summary'),str) and entry['summary'].strip():message(session,role,'all','finding',entry['summary'][:2000])
                    parsed={'results':combined}
                    if errors:parsed['error']='; '.join(errors)
                    response=json.dumps(parsed)
                    if parsed.get('error'):message(session,'orchestrator','human','blocker','Specialist runtime issue: '+str(parsed['error'])[:1600])
                    for entry in parsed.get('results',[]):
                        index=entry.get('task_index',0);task=tasks[index] if isinstance(index,int) and index<len(tasks) else tasks[0]
                        role=role_for(task['goal']);summary=entry.get('summary')
                        if isinstance(summary,str) and summary.strip():
                            message(session,role,'orchestrator','result',summary[:2000]);session.completed_roles.add(role)
                            for request in task['_requests']:
                                message(session,role,request['sender'],'result',('Reply to '+request['id']+': '+summary)[:2000])
                                session.pending_messages.pop(request['id'],None)
                                if request['sender'] not in ('orchestrator','human','all'):
                                    if not hasattr(session,'reply_readers'):session.reply_readers={}
                                    session.reply_readers.setdefault(request['sender'],[]).append({'request':request,'answer':summary[:2000]})
                            for receipt in task.get('_reply_receipts',[]):
                                readers=getattr(session,'reply_readers',{}).get(role,[])
                                if receipt in readers:readers.remove(receipt)
                                if not readers:getattr(session,'reply_readers',{}).pop(role,None)
                        else:message(session,role,'orchestrator','blocker','Specialist returned no usable summary; inspect runtime errors and retry explicitly.')
                    pending=list(getattr(session,'pending_messages',{}).values())
                    depth=getattr(session,'routing_depth',0)
                    readers=getattr(session,'reply_readers',{})
                    if (pending or readers) and depth<2:
                        session.routing_depth=depth+1
                        try:
                            roles=sorted({m['recipient'] for m in pending}|set(readers))
                            follow=json.loads(dispatch(self,{'tasks':[{'goal':'['+role+'] Answer the attached questions and resolve draft feedback. Cite evidence; explicitly report unavailable facts. Send requests for corrections to the relevant specialist.','context':'Read the supplied shared exchanges and questions_to_answer.'} for role in roles]}))
                            parsed['follow_up']=follow
                            response=json.dumps(parsed)
                        finally:session.routing_depth=depth
                    elif pending or readers:
                        message(session,'orchestrator','human','blocker','Specialist follow-up budget reached. Unanswered questions block saving; review the messages or retry.')
                    return response
                except ValueError as e:return json.dumps({'error':str(e)})
            agent._dispatch_delegate_task=types.MethodType(dispatch,agent)
        prompts = {f.stem: f.read_text() for f in (project / 'prompts').glob('*.md') if f.stem not in ('orchestrator', 'playbook-orchestrator','playbook-discovery') and f.stem.startswith('playbook-') == is_playbook}
        context = {'specialist_instructions': prompts, 'authoritative_policy': payload['authoritative_policy'], 'untrusted_inputs': payload['prospect']} if is_playbook else {'specialist_instructions': prompts, 'untrusted_inputs': payload}
        if discovery:
            search_name=next(n for n in maps_names if 'search_businesses' in n)
            approved_terms=payload['authoritative_policy'][payload['prospect']['campaign']['icp']]['search']
            seeds=[]
            # Several approved search angles supply independent businesses,
            # leaving provider operations available for the discovery agent.
            for term in approved_terms[:3]:
                seeds.append(registry.get_entry(search_name).handler({'search_term':term,'limit':min(10,max(5,session.limit))},task_id=session.root_task_id))
            context['actual_search_results']=seeds
            context['research_pool_target']=session.limit
            context['required_next_action']='Select multiple distinct genuine businesses from actual search results using continere_select_prospect until the pool target or search budget is reached. Each business gets an independent research team. Returning JSON alone does not save it. Search snippets establish no qualification. Continue after duplicates.'
        if session and not discovery:
            tasks=[{'goal':'['+purpose+'_search] Search missing '+purpose+' evidence for the saved business using continere_search_missing_evidence purpose='+purpose+'. Read promising returned sources with continere_read_search_source. Report exact evidence IDs, business identity ambiguity, access limitations and unresolved facts. No invented reviews, ratings, personal cells, qualification, approval or contact.','context':'Read current evidence first. Search exactly once for this purpose; preserve VJ policy.'} for purpose in session.needed_searches()]
            if tasks:agent._dispatch_delegate_task({'tasks':tasks})
            for purpose in session.needed_searches():
                if purpose not in session.search_attempts:session.search_missing(purpose)
            context['followup_searches_completed']=sorted(session.search_attempts)
            context['required_followup']='Read shared evidence and search-agent messages. Researcher/qualifier/writer/QA must review provenance; only supported exact GMB review hooks are allowed. Missing evidence remains null.'
        result = agent.run_conversation(json.dumps(context),task_id=session.root_task_id if session else None)
    response = result.get('final_response', '').strip()
    if not response:
        raise RuntimeError('Hermes subscription returned no final response; inspect provider connection diagnostics')
    if response.startswith('```'):
        response = response.split('\n', 1)[1].rsplit('```', 1)[0]
    value = json.loads(response)
    delegated = 0
    for message in result.get('messages', []):
        for call in message.get('tool_calls', []) or []:
            fn = call.get('function', {})
            if fn.get('name') == 'delegate_task':
                args = json.loads(fn.get('arguments') or '{}')
                delegated += len(args.get('tasks') or [1])
                if session:
                    for task in args.get('tasks') or [args]:session.note('delegation','Verified runtime handoff: '+str(task.get('goal','Specialist investigation'))[:580])
    if session and not discovery and not {'researcher','qualifier','writer','qa'}.issubset(session.completed_roles):raise RuntimeError('Each installed specialist must return findings before completion')
    if not discovery and delegated < 4:
        raise RuntimeError('Expected research, qualification, writer and QA delegation; incomplete run rejected')
    if discovery:
        session.complete_pool()
        if not session.saved:raise RuntimeError('Discovery search returned no new source-backed candidates. Final response: '+response[:1200])
        value={'places':session.selected_places,'discovery_target':session.limit,'discovery_complete':len(session.selected_places)>=session.limit,'discovery_limit_reason':None if len(session.selected_places)>=session.limit else 'Available unique source-returned leads exhausted within the bounded search budget; existing businesses were not duplicated.','agent_trace':['Source-backed discovery queued '+str(len(session.selected_places))+' distinct businesses for independent qualification teams; no contact approved']}
    if session and not session.saved:raise RuntimeError('Agent did not save validated findings through workspace tool')
    if session and not discovery:
        # The workspace tool already validated the extraction. The final chat
        # summary is presentation, not a replacement for that saved contract.
        from gtm.db import connect
        with connect() as conn:
            value=json.loads(conn.execute('SELECT analysis FROM playbook_candidates WHERE id=?',(session.cid,)).fetchone()['analysis'])
    value['agent_trace'] = [f'Hermes delegated {delegated} specialist tasks']+([f'Agent retrieved {session.fetched} business pages and saved validated findings through workspace tools'] if session else [])
    print('CONTINERE_RESULT=' + json.dumps(value))

if __name__ == '__main__':
    main()
