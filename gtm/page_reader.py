"""Cheap HTTP first; bounded local browser fallback for thin/dynamic pages."""
from . import providers

def fetch_page(url, *, render=False, interaction='none', acquire_browser=None):
    providers.public_target(url)
    static=None;failure=None
    if not render:
        try:
            static=providers.fetch_website(url)
            text=static.get('text','').strip()
            dynamic=any(marker in text.lower() for marker in ('enable javascript','javascript is required','please turn javascript on'))
            if len(text)>=200 and not dynamic:
                return {**static,'reader':'http','browser_attempted':False}
        except (ValueError,OSError) as exc:
            failure=str(exc)
    if acquire_browser:acquire_browser()
    from . import headless_reader
    try:
        result=headless_reader.read_page(url,interaction=interaction)
        return {**result,'reader':'playwright','browser_attempted':True,'http_failure':failure}
    except (ValueError,OSError) as exc:
        if static and not render:
            return {**static,'reader':'http','browser_attempted':True,'browser_failure':str(exc),'limited_content':True}
        raise ValueError('Public page retrieval failed; local browser reported: '+str(exc)) from None
