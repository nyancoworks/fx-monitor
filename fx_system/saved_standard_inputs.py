"""Lossless standard-input tables for bounded private saved views only."""
from copy import deepcopy
import json

SCHEMA='saved_standard_inputs_v1'


def _json(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _pack_input(value):
    value=deepcopy(value)
    for role in ('base','trigger','h1_setup','m5_timing'):
        frame=value.get(role,{})
        bars=frame.get('bars')
        if not bars:continue
        columns=sorted(bars[0])
        if any(not isinstance(b,dict) or sorted(b)!=columns for b in bars):continue
        frame['bars']={'columns':columns,'values':[[b[k] for k in columns] for b in bars]}
    return value


def _expand_input(value):
    value=deepcopy(value)
    if not isinstance(value,dict):raise ValueError('invalid standard input table')
    for role in ('base','trigger','h1_setup','m5_timing'):
        frame=value.get(role,{})
        bars=frame.get('bars')
        if not isinstance(bars,dict):continue
        if set(bars)!={'columns','values'}:raise ValueError('invalid candle columns')
        cols,values=bars['columns'],bars['values']
        if (not isinstance(cols,list) or not cols or any(not isinstance(k,str) for k in cols)
                or cols!=sorted(set(cols)) or not set(cols)<={'timestamp','open','high','low','close','session_end_utc'}
                or not isinstance(values,list) or len(values)>10000
                or any(not isinstance(v,list) or len(v)!=len(cols) for v in values)):
            raise ValueError('invalid candle table')
        frame['bars']=[dict(zip(cols,v)) for v in values]
    return value


def pack(value):
    tables=[];indices={}
    def walk(obj):
        if isinstance(obj,list):return [walk(v) for v in obj]
        if not isinstance(obj,dict):return obj
        out={}
        for k,v in obj.items():
            if k=='standard_inputs' and isinstance(v,dict) and {'base','trigger','evaluated_at'}<=set(v):
                key=_json(v)
                if key not in indices:
                    if len(tables)>=64:raise ValueError('too many standard input tables')
                    indices[key]=len(tables);tables.append(_pack_input(v))
                out[k]={'table_index':indices[key]}
            else:out[k]=walk(v)
        return out
    body=walk(value)
    return {'schema':SCHEMA,'value':body,'standard_inputs':tables} if tables else deepcopy(value)


def unpack(packed,*,max_expanded_bytes):
    if (not isinstance(packed,dict) or set(packed)!={'schema','value','standard_inputs'}
            or packed['schema']!=SCHEMA or not isinstance(packed['standard_inputs'],list)
            or not 1<=len(packed['standard_inputs'])<=64):
        raise ValueError('invalid standard table layout')
    tables=[];sizes=[]
    for v in packed['standard_inputs']:
        v=_expand_input(v);tables.append(v);sizes.append(len(_json(v)))
        if sum(sizes)>max_expanded_bytes:raise ValueError('standard tables exceed expansion bound')
    used=set();expanded_size=len(_json(packed['value']))
    # Bound expanded references before allocating copies; reject nested/unknown references.
    def check(obj):
        nonlocal expanded_size
        if isinstance(obj,list):
            for v in obj:check(v)
        elif isinstance(obj,dict):
            for k,v in obj.items():
                if k=='standard_inputs':
                    if (not isinstance(v,dict) or set(v)!={'table_index'}
                            or type(v['table_index']) is not int or not 0<=v['table_index']<len(tables)):
                        raise ValueError('invalid standard table reference')
                    idx=v['table_index'];used.add(idx);expanded_size+=sizes[idx]-len(_json(v))
                    if expanded_size>max_expanded_bytes:raise ValueError('saved view exceeds expansion bound')
                else:check(v)
    check(packed['value'])
    if used!=set(range(len(tables))):raise ValueError('unused standard input table')
    def walk(obj):
        if isinstance(obj,list):return [walk(v) for v in obj]
        if not isinstance(obj,dict):return obj
        return {k:deepcopy(tables[v['table_index']]) if k=='standard_inputs' else walk(v) for k,v in obj.items()}
    return walk(packed['value'])
