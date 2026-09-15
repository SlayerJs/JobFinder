"""Load user-owned search criteria without embedding an applicant profile in code."""
import os
from datetime import date
from pathlib import Path
import yaml

SOURCES = {'linkedin','hellowork','apec','lesjeudis','francetravail','welcome_to_the_jungle'}


def load_config(path=None):
    explicit = path or os.getenv('JOBFINDER_CONFIG')
    selected = Path(explicit) if explicit else next(
        (p for p in (Path('config.local.yaml'),Path('config.yaml')) if p.is_file()),
        Path(__file__).resolve().parents[1] / 'config.example.yaml')
    with selected.open(encoding='utf-8') as stream:
        config = yaml.safe_load(stream)
    validate_config(config)
    return config


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('Configuration must be a YAML mapping')
    sources = config.get('sources')
    if not isinstance(sources,list) or not sources or any(not isinstance(s,str) or s not in SOURCES for s in sources):
        raise ValueError('sources must be a nonempty list of supported source names')
    profiles = config.get('search_profiles')
    if not isinstance(profiles,list) or not profiles:
        raise ValueError('At least one search profile is required')
    for profile in profiles:
        if not isinstance(profile,dict) or not isinstance(profile.get('keyword'),str) or not profile['keyword'].strip():
            raise ValueError('Each profile needs a nonempty keyword')
        if not isinstance(profile.get('location',''),str):
            raise ValueError('Profile location must be a string')
        pages=profile.get('max_pages',10)
        if type(pages) is not int or pages < 1:
            raise ValueError('max_pages must be a positive integer')
    criteria=config.get('criteria',{})
    if not isinstance(criteria,dict) or not (criteria.get('instructions') or criteria.get('required')):
        raise ValueError('Set criteria.required or criteria.instructions before evaluation')
    if 'instructions' in criteria and not isinstance(criteria['instructions'],str):
        raise ValueError('criteria.instructions must be text')
    for values in (criteria.get('required',[]),config.get('custom_ai_rules',[]),config.get('preferences',[])):
        if not isinstance(values,list) or any(not isinstance(v,str) for v in values):
            raise ValueError('Rules and preferences must be lists of strings')
    tiers=criteria.get('tiers',{})
    if not isinstance(tiers,dict) or any(str(k) not in {'1','2','3','4'} or not isinstance(v,str) for k,v in tiers.items()):
        raise ValueError('Tier descriptions must map tiers 1–4 to text')
    target=config.get('target',{})
    if not isinstance(target,dict):
        raise ValueError('target must be a mapping')
    dates=[]
    for key in ('start_date','end_date'):
        value=target.get(key)
        dates.append(date.fromisoformat(str(value)) if value else None)
    if all(dates) and dates[0] > dates[1]:
        raise ValueError('Start date must not follow end date')
    if target.get('missing_date','review') not in {'review','flexible'}:
        raise ValueError('missing_date must be review or flexible')
    options=config.get('source_options',{})
    if not isinstance(options,dict) or any(k != 'apec' or not isinstance(v,dict) or set(v)-{'contract_filter'} for k,v in options.items()):
        raise ValueError('Only source_options.apec.contract_filter is supported')


def build_criteria(config):
    criteria=config['criteria']
    parts=['Apply the configured rules to the actual offered role. Do not infer applicant nationality, eligibility, or preferred industry beyond these rules.']
    if criteria.get('instructions'):
        parts.append(criteria['instructions'])
    required=criteria.get('required',[])+config.get('custom_ai_rules',[])
    if required:
        parts.append('Required rules (all must be met):\n'+'\n'.join('- '+rule for rule in required))
    target=config.get('target',{})
    if target.get('start_date') or target.get('end_date'):
        parts.append(f"Target start date: {target.get('start_date') or 'no lower bound'} through {target.get('end_date') or 'no upper bound'}. This overrides any other date window in the rules. If no start date is stated, " + ('treat the date as flexible.' if target.get('missing_date','review')=='flexible' else 'return REVIEW.'))
    tiers=criteria.get('tiers',{})
    if tiers:
        parts.append('Approved job tiers:\n'+'\n'.join(f'Tier {k}: {v}' for k,v in sorted(tiers.items(),key=lambda item:str(item[0]))))
    elif not criteria.get('instructions'):
        parts.append('Approved tiers: 1 direct match, 2 strong match, 3 adjacent match, 4 meets only required rules.')
    preferences=config.get('preferences',[])
    if preferences:
        parts.append('Ranking preferences (never reject solely for these):\n'+'\n'.join('- '+p for p in preferences))
    return '\n\n'.join(parts)
