"""Prompt geography is discovery scope, never a verified prospect timezone."""
import re
NATIONAL=re.compile(r"\b(?:nationwide|nation wide|us[- ]wide|usa[- ]wide|across (?:the )?(?:us|usa|united states)|anywhere in (?:the )?(?:us|usa|united states))\b",re.I)
STOP=re.compile(r"\s+(?:and|then|to|that|which|with|who|for|offering|matching|meeting|using|prepare|draft|research|please)\b|[;!?\n]",re.I)
GENERIC={'the us','us','usa','the usa','united states','the united states','america','the country','my city','my area','me','here'}
def geography(prompt):
 if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>1500:raise ValueError('Enter a task under 1500 characters')
 if NATIONAL.search(prompt):return {'city':'United States','scope':'national','source':'prompt'}
 # Explicit location phrases accept arbitrary cities; task clauses are excluded.
 match=re.search(r"\b(?:in|near|around|within|across|located in|based in)\s+(.+)",prompt,re.I)
 if match and not re.match(r'(?:accordance|line|order|the review|this review|the script|this script)\b',match.group(1),re.I):
  location=STOP.split(match.group(1),maxsplit=1)[0].strip(' .,:')
  if location.lower() in GENERIC:return {'city':'United States','scope':'national','source':'prompt'}
  if location and len(location)<=160 and not re.search(r'\b(?:a|an|the) (?:draft|review|website|business|spa|dietitian|outreach|script|evidence)\b',location,re.I):
   return {'city':location,'scope':'regional','source':'prompt'}
 # Bare title-cased places before/after the business category.
 bare=re.search(r'\b(?:spas?|dietitians?|businesses|prospects?|providers?)\s+([A-Z][a-zA-Z]+(?:[ ,]+[A-Z][a-zA-Z]+){0,3})(?=\s+(?:and|then|to|with|for)\b|[.!?]|$)',prompt)
 if bare:return {'city':bare.group(1).strip(' ,'),'scope':'regional','source':'prompt'}
 before=re.search(r'([A-Z][a-z]+(?:[ ,]+[A-Z][a-z]+){0,3})\s+(?:spas?|dietitians?)\b',prompt)
 if before:
  place=re.sub(r'^(?:Find|Search|Discover|Draft|Research)\s+','',before.group(1)).strip()
  if place and place not in ('Find','Search','Discover','Research','Draft','Qualifying','Independent'):return {'city':place,'scope':'regional','source':'prompt'}
 # Common bare city names also work without a preposition. Other places use explicit location phrases.
 for city in ('New York City','New York','Los Angeles','San Francisco','San Diego','San Antonio','Washington DC','Austin','Seattle','Chicago','Boston','Miami','Dallas','Houston','Denver','Atlanta','Phoenix','Portland','Philadelphia','Las Vegas','Nashville','Orlando'):
  if re.search(r'\b'+re.escape(city)+r'\b',prompt,re.I):return {'city':city,'scope':'regional','source':'prompt'}
 return {'city':'United States','scope':'national','source':'default'}
def intent(prompt):
 return 'discover' if re.search(r"\b(?:find|discover|search(?: for)?|look for)\b.{0,55}\b(?:spa|spas|dietitian|dietitians|business|businesses|practice|practices|prospect|prospects|provider|providers)\b|\b(?:new|another|next) (?:prospect|business|spa|practice)\b",prompt,re.I) else 'continue'


def research_batch(prompt):
 """Bound the number investigated, not the number guaranteed qualified."""
 match=re.search(r'\b(?:find|research|investigate|discover|search(?: for)?)\s+(?:up to\s+)?(\d+)\b',prompt,re.I)
 count=int(match.group(1)) if match else 6
 if not 1<=count<=12:raise ValueError('Choose 1–12 businesses per research mission; three teams can work at once')
 return {'limit':count,'team_count':min(3,count)}
