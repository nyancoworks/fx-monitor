import unittest
from copy import deepcopy
from fx_system.archive_inventory import summarize
from fx_system.backtest_release_store import ReleaseWarehouse,open_envelope,envelope
from test_backtest_release_store import MemoryAPI,batches,NOW


class InventoryTests(unittest.TestCase):
    def test_gaps_are_observed_grid_gaps_not_inferred_market_sessions(self):
        rows=[{'timestamp':t,'source':'synthetic'} for t in (0,300,1200)]
        p={'Synthetic/TEST/m5/2030-01':rows};before=deepcopy(p)
        s=summarize(p)['streams'][0]
        self.assertEqual((s['count'],s['missing_grid_intervals'],s['gap_segments']),(3,2,1))
        self.assertEqual(p,before)
        self.assertIsNone(summarize({'Synthetic/TEST/d1/2030-01':rows})['streams'][0]['missing_grid_intervals'])

    def test_same_requests_and_unchanged_cycle_does_not_publish_for_inventory(self):
        api=MemoryAPI();w=ReleaseWarehouse(api)
        w.cycle(batches(),now=NOW,source={'run':1})
        pointer=open_envelope(api.release['body']);self.assertIn('inventory',pointer)
        inv=pointer['inventory'];self.assertEqual(len(inv['bundles']),2)
        self.assertEqual(inv['unknown_bundle_keys'],[])
        for item in inv['bundles'].values():self.assertEqual(item['streams'][0]['count'],1)
        api.reset()
        before=len(api.trace)
        out=w.cycle(batches(),now=NOW,source={'run':2})
        self.assertEqual(out['status'],'unchanged')
        self.assertFalse(any(method in ('UPLOAD','PATCH','DELETE','POST') for method,path in api.trace[before:]))

    def test_old_index_without_inventory_is_upgraded_on_normal_new_data_only(self):
        api=MemoryAPI();w=ReleaseWarehouse(api)
        w.cycle(batches(),now=NOW,source={'run':1})
        api.reset()
        legacy=api.state();legacy.pop('inventory')
        index=w._put(7,'index',envelope(legacy));backup=w._put(7,'backup',envelope(legacy))
        api.release['body']=envelope({'index':index,'backup':backup}).decode()
        api.reset()
        out=w.cycle(batches(NOW+3600),now=NOW+3600,source={'run':2})
        self.assertEqual(out['status'],'persisted')
        self.assertTrue(open_envelope(api.release['body'])['inventory']['bundles'])
