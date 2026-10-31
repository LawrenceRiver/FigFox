"""Local admission estimate, not a provider tokenizer or a hard token bound.

The default window is the 1,048,576 reported by this deployment's HTTP errors.
Different deployments must configure their actual window. Image and text costs
are conservative working estimates; provider accounting remains authoritative.
No evidence is cut and no extra HTTP request is made to count tokens.
"""
import os


def _positive_setting(name, default):
    value=int(os.environ.get(name,default))
    if value<=0:raise ValueError(name+' must be positive')
    return value


def _measure(value):
    counts={'text_utf8_bytes':0,'image_count':0}
    def count(value):
        if isinstance(value,dict):
            if value.get('type')=='image_url':
                counts['image_count']+=1
                return  # Encoded image bytes are not text tokens.
            for key,item in value.items():
                counts['text_utf8_bytes']+=len(str(key).encode('utf-8'))+4
                count(item)
        elif isinstance(value,list):
            for item in value:count(item)
        elif isinstance(value,str):counts['text_utf8_bytes']+=len(value.encode('utf-8'))
        elif value is not None:counts['text_utf8_bytes']+=len(str(value))+1
    count(value)
    return counts


def _estimate(counts, message_count):
    return (counts['text_utf8_bytes']+1)//2 + counts['image_count']*4096 + 4096 + message_count*256


def plan_context(messages, tools, *, provider_prefixes=()):
    counts=_measure([messages,tools])
    window=_positive_setting('FLOW_DS_CONTEXT_TOKENS',1048576)
    desired=_positive_setting('FLOW_DS_MAX_OUTPUT_TOKENS',64000)
    safety=32768
    estimate=_estimate(counts,len(messages))
    calibration={}
    matches=[p for p in provider_prefixes if type(p.get('prompt_tokens')) is int and p['prompt_tokens']>0
             and p.get('messages') and messages[:len(p['messages'])]==p['messages']]
    if matches:
        prior=max(matches,key=lambda p:(len(p['messages']),p['prompt_tokens']))
        suffix=messages[len(prior['messages']):]
        # A changed schema is charged in full; no optimistic subtraction.
        extra_tools=[] if tools==prior.get('tools',[]) else tools
        estimate=prior['prompt_tokens']+_estimate(_measure([suffix,extra_tools]),len(suffix))
        calibration={'provider_prefix_prompt_tokens':prior['prompt_tokens'],
                     'provider_prefix_message_count':len(prior['messages'])}
    available=window-estimate-safety
    # Do not shrink output based on a rough estimate: it can truncate valid repairs.
    return {**counts,**calibration,'context_window_tokens':window,'estimated_input_tokens':estimate,
            'exact_token_count':False,'estimator':'utf8_bytes/2 + 4096/image + message overhead',
            'safety_tokens':safety,'requested_output_tokens':desired,'max_output_tokens':desired,
            'estimated_available_output_tokens':max(0,available),
            'status':'admitted' if available>=desired else 'blocked_before_http',
            'evidence_discarded':False}
