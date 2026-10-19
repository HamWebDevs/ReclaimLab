import contextlib
import copy
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from reclaimlab import har_compare
from reclaimlab.cli import main
from reclaimlab.report import create_network_compare
from test_har import archive, entry


class HARCompareTests(unittest.TestCase):
    def test_matches_routes_independently_of_order_and_aggregates_queries(self):
        before = archive(entry(url='https://example.invalid/a?token=private'), entry(url='https://example.invalid/b'), entry(url='https://example.invalid/a?token=other'))
        after = archive(entry(url='https://example.invalid/b'), entry(url='https://example.invalid/a?new=value'))
        result = har_compare.compare(before, after)
        self.assertEqual(result['summary']['routes'], 2)
        self.assertEqual(result['routes'][0]['delta']['requests']['change'], -1)
        self.assertEqual(result['routes'][1]['state'], 'unchanged')
        self.assertEqual(result['delta']['body_bytes']['change'], -1000)
        text = json.dumps(result)
        for private in ['example.invalid', 'token=', 'private', 'other', '?new=', 'value']:
            # The word "private" appears in the interpretation of matching keys.
            if private != 'private': self.assertNotIn(private, text)

    def test_origins_default_ports_and_methods_are_distinct(self):
        before = archive(entry(url='https://example.invalid:443/a'))
        after = archive(entry(url='https://example.invalid/a'), entry(url='https://different.invalid/a'))
        after['log']['entries'][0]['request']['method'] = 'POST'
        result = har_compare.compare(before, after)
        self.assertEqual((result['summary']['added'], result['summary']['removed']), (2, 1))
        self.assertEqual(len(result['origins']), 2)
        unchanged = har_compare.compare(before, archive(entry(url='https://example.invalid/a')))
        self.assertEqual(unchanged['summary']['unchanged'], 1)

    def test_unknown_measurements_never_become_zero_deltas(self):
        before, after = archive(entry()), archive(entry())
        after['log']['entries'][0]['response']['bodySize'] = -1
        after['log']['entries'][0]['timings']['wait'] = -1
        result = har_compare.compare(before, after)
        for metric in ('body_bytes', 'wait_p95_ms'):
            self.assertEqual(result['delta'][metric]['state'], 'unknown')
            self.assertIsNone(result['delta'][metric]['change'])
        self.assertEqual(result['delta']['requests']['change'], 0)

    def test_inconsistent_phases_keep_wait_delta_unknown(self):
        before, after = archive(entry()), archive(entry())
        after['log']['entries'][0]['timings']['connect'] = 300
        result = har_compare.compare(before, after)
        self.assertIsNone(result['delta']['wait_p95_ms']['after'])
        self.assertEqual(result['after']['summary']['timing_mismatches'], 1)

    def test_absent_routes_have_zero_counts_but_no_invented_waits(self):
        result = har_compare.compare(archive(entry(url='https://example.invalid/old')), archive(entry(url='https://example.invalid/new')))
        self.assertEqual(result['routes'][0]['state'], 'removed')
        self.assertEqual(result['routes'][1]['state'], 'added')
        self.assertEqual(result['routes'][1]['delta']['body_bytes']['change'], 1000)
        self.assertIsNone(result['routes'][1]['delta']['body_bytes']['percent'])
        self.assertIsNone(result['routes'][1]['delta']['wait_p95_ms']['change'])

    def test_full_matching_keys_are_not_truncated_display_labels(self):
        prefix = 'https://example.invalid/' + 'a' * 450
        result = har_compare.compare(archive(entry(url=prefix+'x')), archive(entry(url=prefix+'y')))
        self.assertEqual((result['summary']['added'], result['summary']['removed']), (1, 1))
        self.assertNotIn('a'*100, json.dumps(result))

    def test_opt_in_labels_still_discard_credentials_queries_and_fragments(self):
        capture = archive(entry(url='https://NAME:PASSWORD@example.invalid/private-path?token=TOKEN#FRAGMENT'))
        capture['log']['entries'][0]['request']['headers'] = [{'name':'Cookie', 'value':'COOKIE'}]
        result = har_compare.compare(capture, capture, include_paths=True)
        text = json.dumps(result)
        self.assertIn('example.invalid/private-path', text)
        for private in ['NAME', 'PASSWORD', 'TOKEN', 'FRAGMENT', 'COOKIE']:
            self.assertNotIn(private, text)

    def test_explicit_multi_page_selection_is_kept_independent(self):
        capture = archive(entry(), entry(url='https://example.invalid/b'))
        capture['log']['pages'] = [{'id':'a'}, {'id':'b'}]
        for row, identity in zip(capture['log']['entries'], ('a','b')):row['pageref']=identity
        with self.assertRaises(ValueError):har_compare.compare(capture,capture)
        result=har_compare.compare(capture,capture,before_page=1,after_page=2)
        self.assertEqual(result['summary']['routes'],2)
        self.assertEqual(result['before']['scope']['entries_outside_selected_page'],1)

    def test_synthetic_and_compact_results_keep_scope_and_coverage(self):
        result = har_compare.synthetic()
        self.assertTrue(result['synthetic'])
        brief = har_compare.compact(result)
        self.assertNotIn('routes', brief)
        self.assertIn('body_known_requests', brief['before']['summary'])
        self.assertLessEqual(len(brief['top_changes']), 20)

    def test_cli_outputs_are_exclusive_and_do_not_treat_growth_as_a_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=root/'a.har';b=root/'b.har';out=root/'report.html'
            a.write_text(json.dumps(archive(entry())))
            changed=archive(entry());changed['log']['entries'][0]['response']['bodySize']=2000
            b.write_text(json.dumps(changed))
            stdout,stderr=io.StringIO(),io.StringIO()
            with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                code=main(['har-compare',str(a),str(b),'--json','--output',str(out)])
            self.assertEqual(code,0,stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())['delta']['body_bytes']['change'],1000)
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['har-compare',str(a),str(b),'--output',str(out)]),2)

    def test_html_embeds_inert_json_and_text_only_labels(self):
        result=har_compare.synthetic();result['routes'][0]['label']='</script><img src=x onerror=EVIL()>'
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'report.html';create_network_compare(result,out);text=out.read_text()
            self.assertNotIn('</script><img',text)
            self.assertNotIn('innerHTML',text)
            raw=re.search(r'<script id="compare-data" type="application/json">(.*?)</script>',text,re.S)[1]
            self.assertEqual(json.loads(raw)['routes'][0]['label'],result['routes'][0]['label'])

    @unittest.skipUnless(shutil.which('node'),'Node is optional for report interaction checks')
    def test_javascript_filters_details_and_stable_capture_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'report.html';create_network_compare(har_compare.synthetic(),out)
            script=r'''const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');const html=fs.readFileSync(process.argv[1],'utf8');function node(){let text='';const n={children:[],value:'',hidden:false,appendChild(x){this.children.push(x);return x;}};Object.defineProperty(n,'textContent',{get(){return text},set(v){text=v;this.children=[]}});return n;}const nodes={};for(const m of html.matchAll(/id="([^"]+)"/g))nodes[m[1]]=node();nodes['compare-data'].textContent=html.match(/<script id="compare-data" type="application\/json">([\s\S]*?)<\/script>/)[1];nodes.state.value='all';nodes.sort.value='body';vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],{document:{getElementById:id=>nodes[id],createElement:node},Intl,console});const count=nodes['route-rows'].children.length;assert(count>0);const summary=nodes.requests.textContent;nodes.state.value='added';nodes.state.onchange();assert.equal(nodes['route-rows'].children.length,1);assert.equal(nodes.requests.textContent,summary);nodes['route-rows'].children[0].children[0].children[0].onclick();assert.equal(nodes.detail.hidden,false);assert(nodes['detail-data'].textContent.includes('route-'));nodes.search.value='no match';nodes.search.oninput();assert.equal(nodes['page-state'].textContent,'0 matching routes');nodes.reset.onclick();assert.equal(nodes['route-rows'].children.length,count);'''
            result=subprocess.run(['node','-e',script,str(out)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
