"""Synthetic offline storage fault tests. No market calls or real credentials."""
import copy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from fx_system.backtest_partition import canonical
from fx_system.backtest_release_store import (
    GitHubStorage, ReleaseWarehouse, REPOSITORY, TAG, digest, envelope,
    open_envelope, decode_bundle)

NOW=int(datetime(2030,1,2,tzinfo=timezone.utc).timestamp())


def batches(now=NOW, price=100):
    return [{'provider':'Synthetic','pair':'TEST','tf':tf,'month':datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m'),
             'rows':[{'timestamp':now-seconds,'open':price,'high':price+2,'low':price-2,'close':price+1,
                      'source':'synthetic','captured_at':now,'capture_basis':'saved_cache_known_by'}]}
            for tf,seconds in (('m5',300),('h1',3600))]


class MemoryAPI:
    def __init__(self):
        self.calls=0;self.remaining=5000;self.release=None;self.assets={};self.bytes={};self.next_id=1
        self.private=True;self.fail=None;self.trace=[]

    def reserve(self,n):
        if self.calls+n>64 or self.remaining-n<=200:
            raise ValueError('budget')

    def request(self,method,path,**kw):
        self.reserve(1);self.calls+=1;self.remaining-=1;self.trace.append((method,path))
        if self.fail and self.fail(method,path,kw):
            raise ValueError('injected')
        if path=='':return {'full_name':REPOSITORY,'private':self.private}
        if path=='/releases/tags/'+TAG:return copy.deepcopy(self.release)
        if method=='POST' and path=='/releases':
            self.release={'id':7,**kw['body']};return copy.deepcopy(self.release)
        if method=='GET' and path.startswith('/releases/7/assets?'):
            page=int(path.split('page=')[-1]);return copy.deepcopy(list(self.assets.values())[(page-1)*100:page*100])
        if method=='UPLOAD':
            name=path.split('name=')[1];raw=kw['raw'];aid=self.next_id;self.next_id+=1
            self.assets[aid]={'id':aid,'name':name,'state':'uploaded','digest':'sha256:'+digest(raw),'size':len(raw)}
            self.bytes[aid]=raw;return copy.deepcopy(self.assets[aid])
        if path=='/releases/7':
            if method=='PATCH':self.release.update(kw['body'])
            return copy.deepcopy(self.release)
        if path.startswith('/releases/assets/'):
            aid=int(path.rsplit('/',1)[1])
            if method=='DELETE':del self.assets[aid];del self.bytes[aid];return None
            return self.bytes[aid]
        raise AssertionError((method,path))

    def reset(self):
        self.calls=0;self.trace=[];self.fail=None

    def state(self):
        pointer=open_envelope(self.release['body'])
        return open_envelope(self.bytes[pointer['index']['id']])


class ReleaseTests(unittest.TestCase):
    def cycle(self,api,rows=None,now=NOW):
        return ReleaseWarehouse(api).cycle(rows if rows is not None else batches(now),now=now,source={'synthetic':True})

    def test_initial_increment_duplicate_and_restore(self):
        api=MemoryAPI();r=self.cycle(api)
        self.assertEqual(r['added'],2);self.assertLessEqual(api.calls,64)
        self.assertEqual(len(api.assets),4)
        state=api.state();self.assertEqual(len(state['bundles']),2)
        for key,ref in state['bundles'].items():
            self.assertEqual(len(decode_bundle(api.bytes[ref['id']],key,NOW)),1)
        api.reset();r=self.cycle(api)
        self.assertEqual(r['status'],'unchanged');self.assertFalse(any(m in ('UPLOAD','PATCH','DELETE') for m,p in api.trace))
        api.reset();r=self.cycle(api,now=NOW+3600)
        self.assertEqual(r['added'],2);self.assertEqual(r['deleted_derived_assets'],4)
        self.assertEqual(len(api.assets),4)

    def test_conflict_preserves_pointer_and_objects(self):
        api=MemoryAPI();self.cycle(api);before=(api.release['body'],copy.deepcopy(api.bytes));api.reset()
        with self.assertRaises(ValueError):self.cycle(api,batches(price=200))
        self.assertEqual((api.release['body'],api.bytes),before)
        self.assertFalse(any(m in ('UPLOAD','PATCH','DELETE') for m,p in api.trace))

    def test_expiry_and_pinned_research_survive(self):
        api=MemoryAPI();self.cycle(api);state=api.state()
        fixed=state['bundles']['m5/2030-01'];state['pins']={'fixed_study':{'m5/2030-01':fixed}}
        # Simulate a prior, valid researcher publication of an immutable pin.
        ptr=open_envelope(api.release['body']);warehouse=ReleaseWarehouse(api);warehouse._inventory(7)
        for key in ('index','backup'):
            ptr[key]=warehouse._put(7,key,envelope(state))
        api.release['body']=envelope(ptr).decode();api.reset()
        future=int(datetime(2034,2,1,tzinfo=timezone.utc).timestamp())
        self.cycle(api,[],future);new=api.state()
        self.assertNotIn('m5/2030-01',new['bundles']);self.assertIn('h1/2030-01',new['bundles'])
        self.assertIn(fixed['id'],api.bytes);self.assertEqual(new['pins'],state['pins'])

    def test_quota_failure_does_not_delete_to_fit(self):
        api=MemoryAPI();self.cycle(api);before=copy.deepcopy(api.bytes);api.reset()
        with self.assertRaises(ValueError):
            ReleaseWarehouse(api,quota=sum(len(x) for x in before.values())+1).cycle(batches(NOW+3600),now=NOW+3600,source={'x':1})
        self.assertEqual(api.bytes,before)
        self.assertFalse(any(m in ('UPLOAD','PATCH','DELETE') for m,p in api.trace))

    def test_private_destination_and_unknown_assets_fail_closed(self):
        api=MemoryAPI();api.private=False
        with self.assertRaises(ValueError):self.cycle(api)
        self.assertIsNone(api.release)
        api=MemoryAPI();self.cycle(api);api.reset();a=next(iter(api.assets.values()));a['name']='original-checkpoint'
        with self.assertRaises(ValueError):self.cycle(api)
        self.assertFalse(any(m=='DELETE' for m,p in api.trace))

    def test_backup_corruption_blocks_uploads_and_cleanup(self):
        api=MemoryAPI();self.cycle(api);ptr=open_envelope(api.release['body']);api.bytes[ptr['backup']['id']]=b'corrupt'
        api.reset()
        with self.assertRaises(ValueError):self.cycle(api,now=NOW+3600)
        self.assertFalse(any(m in ('UPLOAD','PATCH','DELETE') for m,p in api.trace))

    def test_upload_failure_and_pointer_failure_keep_previous_recoverable(self):
        for fail_method in ('UPLOAD','PATCH'):
            with self.subTest(fail_method=fail_method):
                api=MemoryAPI();self.cycle(api);previous=api.release['body'];old_bytes=copy.deepcopy(api.bytes);api.reset()
                api.fail=lambda m,p,k:m==fail_method
                with self.assertRaises(ValueError):self.cycle(api,now=NOW+3600)
                self.assertEqual(api.release['body'],previous)
                self.assertTrue(all(api.bytes[k]==v for k,v in old_bytes.items()))
                self.assertFalse(any(m=='DELETE' for m,p in api.trace))

    def test_post_publish_verification_failure_keeps_old_and_new_assets(self):
        api=MemoryAPI();self.cycle(api);old=set(api.assets);api.reset()
        reads=0
        def fail(m,p,k):
            nonlocal reads
            if m=='GET' and p=='/releases/7':reads+=1
            return reads==2
        api.fail=fail
        with self.assertRaises(ValueError):self.cycle(api,now=NOW+3600)
        self.assertTrue(old<=set(api.assets));self.assertFalse(any(m=='DELETE' for m,p in api.trace))

    def test_budget_stops_before_upload(self):
        api=MemoryAPI();self.cycle(api);api.reset();api.calls=55
        with self.assertRaises(ValueError):self.cycle(api,now=NOW+3600)
        self.assertLessEqual(api.calls,64);self.assertFalse(any(m in ('UPLOAD','DELETE') for m,p in api.trace))


class Response:
    def __init__(self,status=200,headers=None,body=b'{}'):
        self.status_code=status;self.headers=headers or {};self.body=body
    def iter_content(self,size):yield self.body
    def close(self):pass


class Session:
    def __init__(self,responses):self.responses=iter(responses);self.calls=[]
    def request(self,method,url,**kw):self.calls.append((method,url,kw));return next(self.responses)


class TransportTests(unittest.TestCase):
    def test_binary_redirect_counted_and_credential_removed(self):
        s=Session([Response(302,{'Location':'https://release-assets.githubusercontent.com/synthetic?signature=fake','X-RateLimit-Remaining':'4000'}),Response(body=b'test')])
        api=GitHubStorage('synthetic-token',session=s)
        self.assertEqual(api.request('GET','/releases/assets/1',binary=True),b'test')
        self.assertEqual(api.calls,2);self.assertNotIn('Authorization',s.calls[1][2]['headers'])
        self.assertTrue(all(c[2]['allow_redirects'] is False for c in s.calls))

    def test_redirect_to_arbitrary_host_rejected(self):
        s=Session([Response(302,{'Location':'https://example.com/leak'})])
        with self.assertRaises(ValueError):GitHubStorage('synthetic-token',session=s).request('GET','/releases/assets/1',binary=True)
        self.assertEqual(len(s.calls),1)

    def test_rate_reserve_and_no_retry(self):
        s=Session([Response(headers={'X-RateLimit-Remaining':'200'})]);a=GitHubStorage('synthetic-token',session=s)
        a.request('GET','')
        with self.assertRaises(ValueError):a.request('GET','')
        self.assertEqual(len(s.calls),1)
        s=Session([Response(503)])
        with self.assertRaises(ValueError):GitHubStorage('synthetic-token',session=s).request('GET','')
        self.assertEqual(len(s.calls),1)


if __name__=='__main__':unittest.main()
