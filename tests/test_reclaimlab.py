"""Native counter maths, trace boundaries, evidence, experiments and offline output."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from reclaimlab.analysis import analyse, quantile
from reclaimlab.cli import main
from reclaimlab.demo import synthetic
from reclaimlab.experiment import compare
from reclaimlab.native import Linux, collector, delta, linux_cpu, linux_process, pressure
from reclaimlab.record import record
from reclaimlab.report import create, timeline
from reclaimlab.trace import exclusive, load, signature, write_row


class TempTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self,trace,name='trace.jsonl'):
        path=self.root/name
        with exclusive(path) as stream:
            for row in [trace['header'],*trace['samples'],*trace['markers'],trace['footer']]:
                write_row(stream,row)
        return path

    def cli(self,argv):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=main(argv)
        return code,out.getvalue(),err.getvalue()


class NativeTests(TempTest):
    def test_cpu_excludes_guest_and_keeps_iowait_separate(self):
        cpu=linux_cpu('cpu 100 10 40 200 30 5 5 10 900 900\n')
        self.assertEqual(cpu,{'total':400,'idle':200,'iowait':30,'steal':10})

    def test_psi_uses_absolute_counters(self):
        self.assertEqual(pressure('some avg10=99 total=1234\nfull avg10=0 total=50\n'),{'some':1234,'full':50})

    def test_process_names_with_parentheses_and_spaces(self):
        fields=['S']+['0']*21
        fields[11],fields[12],fields[19],fields[21]='200','100','123','10'
        result=linux_process('42 (strange ) process) '+' '.join(fields),100,4096)
        self.assertEqual(result['name'],'strange ) process')
        self.assertEqual(result['cpu_seconds'],3)
        self.assertEqual(result['rss_bytes'],40960)

    def snapshots(self):
        old={'clock':1,'cpu':{'total':100,'idle':50,'iowait':10},'memory_total':1000,'memory_available':100,'psi':{'memory':{'some':100}},'disks':{'sda':{'busy_ms':100}},'swap_in':1000,'swap_out':1000,'processes':{'1':{'start':'a','cpu_seconds':1,'name':'browser','rss_bytes':100}}}
        new=copy.deepcopy(old);new.update(clock=2,memory_available=0,swap_in=2000)
        new['cpu']={'total':200,'idle':70,'iowait':20}
        new['psi']['memory']['some']=100100
        new['disks']['sda']['busy_ms']=600
        new['processes']['1']['cpu_seconds']=2
        return old,new

    def test_counter_delta_units_and_zero_available_memory(self):
        old,new=self.snapshots();metrics,processes=delta(new,old,2)
        self.assertEqual(metrics['cpu_pct'],70)
        self.assertEqual(metrics['iowait_pct'],10)
        self.assertEqual(metrics['memory_available_pct'],0)
        self.assertEqual(metrics['memory_pressure_pct'],10)
        self.assertEqual(metrics['disk_busy_pct'],50)
        self.assertEqual(metrics['swap_in_Bps'],1000)
        self.assertEqual(processes[0]['cpu_pct'],50)

    def test_reset_counters_and_reused_pids_are_not_spikes(self):
        old,new=self.snapshots();new['cpu']['total']=1;new['swap_in']=1
        new['processes']['1']['start']='reused'
        metrics,processes=delta(new,old)
        self.assertIsNone(metrics['cpu_pct']);self.assertIsNone(metrics['swap_in_Bps']);self.assertEqual(processes,[])

    def test_stolen_cpu_time_is_not_reported_as_busy_work(self):
        old,new=self.snapshots();old['cpu']['steal']=0;new['cpu']['steal']=20
        metrics,_=delta(new,old)
        self.assertEqual(metrics['cpu_pct'],50)
        self.assertEqual(metrics['steal_pct'],20)

    def test_missing_counters_remain_unknown(self):
        old,new=self.snapshots();new['psi']={};new['disks']={};new['swap_in']=None
        metrics,_=delta(new,old)
        self.assertIsNone(metrics['memory_pressure_pct']);self.assertIsNone(metrics['disk_busy_pct']);self.assertIsNone(metrics['swap_in_Bps'])

    def test_linux_fixture_with_missing_optional_files(self):
        proc,sys=self.root/'proc',self.root/'sys';proc.mkdir();sys.mkdir()
        (proc/'stat').write_text('cpu 1 2 3 40 5 6 7 8\n')
        (proc/'meminfo').write_text('MemTotal: 4096 kB\n')
        result=Linux(proc=proc,sys=sys,page_size=4096,ticks=100).snapshot()
        self.assertEqual(result['memory_total'],4096*1024)
        self.assertIsNone(result['memory_available'])
        self.assertEqual(result['disks'],{})

    def test_capture_error_preserves_samples_and_records_failure(self):
        old, new = self.snapshots()
        backend = mock.Mock(name='backend')
        backend.name = 'fixture'
        backend.description.return_value = {}
        backend.snapshot.side_effect = [old, new, OSError('counter unavailable')]
        path = self.root / 'failed.jsonl'
        with self.assertRaisesRegex(OSError, 'counter unavailable'):
            record(path, seconds=2, interval=.2, backend=backend)
        trace = load(path)
        self.assertEqual(len(trace['samples']), 1)
        self.assertEqual(trace['footer']['error'], 'OSError: counter unavailable')
        self.assertTrue(any('incomplete' in item for item in analyse(trace)['quality']))

    def test_interrupted_capture_preserves_samples_and_marks_footer(self):
        old, new = self.snapshots()
        backend = mock.Mock(name='backend')
        backend.name = 'fixture'
        backend.description.return_value = {}
        backend.snapshot.side_effect = [old, new, KeyboardInterrupt()]
        path = self.root / 'interrupted.jsonl'
        result = record(path, seconds=2, interval=.2, backend=backend)
        trace = load(path)
        self.assertTrue(result['interrupted'])
        self.assertTrue(trace['footer']['interrupted'])
        self.assertIsNone(trace['footer']['error'])
        self.assertEqual(len(trace['samples']), 1)

    @unittest.skipUnless(platform.system() in {'Linux','Windows'},'Live backend available on Linux/Windows')
    def test_live_native_snapshot_and_short_capture(self):
        backend=collector(processes=True)
        snapshot=backend.snapshot()
        self.assertGreater(snapshot['memory_total'],0)
        self.assertGreater(snapshot['cpu']['total'],0)
        path=self.root/'native.jsonl'
        result=record(path,seconds=2,interval=.25,backend=backend,processes=True)
        self.assertGreater(result['samples'],1)
        trace=load(path)
        self.assertIsNotNone(trace['footer'])
        self.assertFalse(trace['footer']['interrupted'])
        self.assertGreater(analyse(trace)['summary']['wake_observations'],0)


class TraceTests(TempTest):
    def test_trace_roundtrip(self):
        trace=load(self.save(synthetic()))
        self.assertEqual(len(trace['samples']),120)
        self.assertTrue(trace['header']['synthetic'])

    def test_exclusive_output(self):
        path=self.root/'file';path.write_text('keep')
        with self.assertRaises(FileExistsError):
            exclusive(path)
        self.assertEqual(path.read_text(),'keep')

    def test_bad_schema_and_nonfinite_data_rejected(self):
        for index, mutate in enumerate((lambda t:t['header'].update(schema=2),lambda t:t['samples'][0].update(t=-1),lambda t:t['samples'][0]['metrics'].update(cpu_pct=101),lambda t:t['samples'][0]['metrics'].update(power=[]))):
            trace=synthetic();mutate(trace)
            path=self.save(trace,name='bad'+str(index)+'.jsonl')
            with self.assertRaises(ValueError):load(path)

    def test_missing_footer_is_flagged_not_hidden(self):
        path=self.save(synthetic())
        path.write_text('\n'.join(path.read_text().splitlines()[:-1])+'\n')
        trace=load(path)
        self.assertIsNone(trace['footer'])
        self.assertTrue(any('incomplete' in q for q in analyse(trace)['quality']))

    def test_records_after_footer_rejected(self):
        path=self.save(synthetic())
        with path.open('a') as f:f.write('{"type":"marker","t":1,"label":"late"}\n')
        with self.assertRaises(ValueError):load(path)

    def test_counter_name_typo_rejected(self):
        trace=synthetic();trace['samples'][0]['metrics']['made_up_counter']=0
        with self.assertRaises(ValueError):load(self.save(trace))

    def test_file_limit_is_enforced(self):
        path=self.save(synthetic())
        with mock.patch('reclaimlab.trace.MAX_BYTES',1):
            with self.assertRaises(ValueError):load(path)

    def test_marker_after_capture_is_rejected(self):
        trace=synthetic();trace['markers'].append({'type':'marker','t':999,'label':'outside'})
        with self.assertRaises(ValueError):load(self.save(trace))

    def test_invalid_heartbeat_interval_is_rejected(self):
        trace=synthetic();trace['header']['heartbeat_s']=0
        with self.assertRaises(ValueError):load(self.save(trace))

    def test_nonincreasing_sample_clock_rejected(self):
        trace=synthetic();trace['samples'][1]['t']=trace['samples'][0]['t']
        with self.assertRaises(ValueError):load(self.save(trace))


class EvidenceTests(unittest.TestCase):
    def test_known_synthetic_overlap_rules(self):
        report=analyse(synthetic())
        codes={x['code'] for x in report['issues']}
        self.assertTrue({'cpu-coincidence','memory-pressure-overlap','storage-pressure-overlap'}<=codes)
        self.assertTrue(report['synthetic'])

    def test_resource_pressure_without_delays_is_not_claimed_as_cause(self):
        report=analyse(synthetic(improved=True))
        self.assertEqual(report['summary']['delayed_records'],0)
        self.assertEqual(report['issues'],[])

    def test_low_memory_without_paging_is_only_limited_evidence(self):
        trace=synthetic()
        for sample in trace['samples']:
            sample['metrics'].update(memory_pressure_pct=None,swap_in_Bps=None,swap_out_Bps=None)
        findings={x['code']:x for x in analyse(trace)['issues']}
        self.assertEqual(findings['memory-headroom']['strength'],'limited')
        self.assertNotIn('memory-pressure-overlap',findings)

    def test_unknown_metrics_do_not_turn_into_zero_averages(self):
        trace=synthetic()
        for s in trace['samples']:s['metrics']['cpu_pct']=None
        report=analyse(trace)
        self.assertIsNone(report['averages']['cpu_pct']);self.assertEqual(report['coverage']['cpu_pct'],0)

    def test_duration_weighting(self):
        trace=synthetic(seconds=2)
        trace['samples'][0]['dt']=10;trace['samples'][0]['metrics']['cpu_pct']=100
        for s in trace['samples'][1:]:s['metrics']['cpu_pct']=0
        self.assertAlmostEqual(analyse(trace)['averages']['cpu_pct'],1000/11.5)

    def test_marker_selection_and_missing_marker(self):
        report=analyse(synthetic(),around='Video playback starts',radius=2)
        self.assertGreaterEqual(report['selection']['end_s'],15)
        self.assertLessEqual(report['summary']['records'],9)
        with self.assertRaises(ValueError):analyse(synthetic(),around='no such marker')

    def test_temperature_does_not_prove_throttling(self):
        trace=synthetic(improved=True)
        for s in trace['samples']:s['metrics']['temperature_c']=95
        codes={x['code'] for x in analyse(trace)['issues']}
        self.assertIn('temperature-exposure',codes);self.assertNotIn('throttle-counter',codes)

    def test_observer_overhead_and_gaps_flagged(self):
        trace=synthetic();trace['footer']['observer_cpu_s']=10;trace['samples'][1]['dt']=10
        quality=analyse(trace)['quality']
        self.assertTrue(any('CPU time' in q for q in quality));self.assertTrue(any('gaps' in q for q in quality))

    def test_empty_wake_data_stays_unknown(self):
        trace=synthetic()
        for s in trace['samples']:s['wake_lag_ms']=[]
        self.assertIsNone(analyse(trace)['summary']['wake_p95_ms'])


class ExperimentTests(unittest.TestCase):
    def test_detects_large_measured_change_reproducibly(self):
        a,b=synthetic(),synthetic(improved=True)
        first=compare(a,b,iterations=50,seed=9)
        second=compare(a,b,iterations=50,seed=9)
        self.assertEqual(first['verdict'],'lower measured wake delay')
        self.assertEqual(first['bootstrap_interval95_ms'],second['bootstrap_interval95_ms'])
        self.assertLess(first['bootstrap_interval95_ms'][1],0)

    def test_same_trace_is_inconclusive(self):
        trace=synthetic();self.assertEqual(compare(trace,trace,iterations=50)['verdict'],'inconclusive')

    def test_machine_or_workload_changes_block_verdict(self):
        a,b=synthetic(),synthetic(improved=True);b['header']['hardware']['logical_cpus']=8
        result=compare(a,b,iterations=50)
        self.assertEqual(result['verdict'],'not comparable');self.assertIsNone(result['bootstrap_interval95_ms'])
        b=synthetic(improved=True);b['header']['workload']='different task'
        self.assertEqual(compare(a,b,iterations=50)['verdict'],'not comparable')

    def test_power_source_change_is_not_an_improvement_claim(self):
        a,b=synthetic(),synthetic(improved=True)
        for s in b['samples']:s['metrics']['power']='battery'
        self.assertEqual(compare(a,b,iterations=50)['verdict'],'not comparable')

    def test_short_or_partial_runs_not_comparable(self):
        self.assertEqual(compare(synthetic(seconds=5),synthetic(seconds=5),iterations=50)['verdict'],'not comparable')
        a,b=synthetic(),synthetic();b['footer']=None
        self.assertEqual(compare(a,b,iterations=50)['verdict'],'not comparable')

    def test_observer_overhead_blocks_comparison(self):
        a,b=synthetic(),synthetic();a['footer']['observer_cpu_s']=15
        self.assertEqual(compare(a,b,iterations=50)['verdict'],'not comparable')

    def test_changed_instrumentation_blocks_verdict(self):
        a,b=synthetic(),synthetic(improved=True)
        b['header']['heartbeat_s']=.1
        self.assertEqual(compare(a,b,iterations=50)['verdict'],'not comparable')
        b=synthetic(improved=True);b['header']['process_names_enabled']=False
        self.assertEqual(compare(a,b,iterations=50)['verdict'],'not comparable')

    def test_invalid_bootstrap_budget(self):
        with self.assertRaises(ValueError):compare(synthetic(),synthetic(),iterations=5000)


class ReportTests(TempTest):
    def test_report_embeds_data_inertly_and_has_no_external_assets(self):
        trace=synthetic();trace['header']['label']='</script><script>alert(1)</script>'
        trace['markers'][0]['label']='<img src=x onerror=alert(1)>'
        path=self.root/'report.html';create(trace,path)
        html=path.read_text()
        self.assertNotIn('<script>alert(1)</script>',html)
        raw=re.search(r'<script type="application/json" id="report-data">(.*?)</script>',html,re.S).group(1)
        self.assertNotIn('<',raw)
        self.assertEqual(json.loads(raw)['header']['label'],trace['header']['label'])
        self.assertIn("connect-src 'none'",html);self.assertNotIn('src="https://',html)
        self.assertNotIn('.innerHTML',html)

    def test_template_tokens_in_untrusted_labels_do_not_expand(self):
        trace=synthetic();trace['header']['label']='__DATA____TITLE__\n"</script>'
        path=self.root/'report.html';create(trace,path)
        raw=re.search(r'<script type="application/json" id="report-data">(.*?)</script>',path.read_text(),re.S).group(1)
        self.assertEqual(json.loads(raw)['header']['label'],trace['header']['label'])

    def test_downsampling_preserves_extremes_and_is_bounded(self):
        trace=synthetic(seconds=600)
        trace['samples'][711]['wake_lag_ms']=[9999]
        trace['samples'][712]['metrics']['memory_available_pct']=.01
        points=timeline(trace['samples'],buckets=10)
        self.assertLessEqual(len(points),50)
        self.assertEqual(max(p['lag'] for p in points),9999)
        self.assertEqual(min(p['memory'] for p in points),.01)

    def test_cli_report_collision_and_invalid_input(self):
        path=self.root/'keep.html';path.write_text('keep')
        self.assertEqual(self.cli(['demo','--output',str(path)])[0],2)
        self.assertEqual(path.read_text(),'keep')
        self.assertEqual(self.cli(['analyze',str(self.root/'missing')])[0],2)

    def test_demo_and_json_cli(self):
        path=self.root/'demo.html';trace=self.root/'demo.jsonl'
        code,_,err=self.cli(['demo','--output',str(path),'--trace-output',str(trace)])
        self.assertEqual(code,0,err)
        code,out,_=self.cli(['analyze',str(trace),'--json'])
        self.assertEqual(code,0);self.assertTrue(json.loads(out)['synthetic'])

    @unittest.skipUnless(shutil.which('node'),'Node is optional for report interaction tests')
    def test_report_javascript_executes_and_controls_work(self):
        path=self.root/'demo.html';create(synthetic(),path,comparison=compare(synthetic(),synthetic(improved=True),iterations=50))
        document=path.read_text()
        data=json.loads(re.search(r'<script type="application/json" id="report-data">(.*?)</script>',document,re.S).group(1))
        script=re.search(r'<script>\s*(.*?)</script>',document,re.S).group(1)
        harness=r'''
const fs=require('fs'),assert=require('assert'),input=JSON.parse(fs.readFileSync(0,'utf8')),elements={};
const context=new Proxy({},{get:()=>()=>{}});
function element(id){return elements[id]||(elements[id]={children:[],style:{},dataset:{},value:id==='to'?100:0,textContent:'',hidden:false,appendChild(x){this.children.push(x)},setAttribute(k,v){this[k]=v},getContext(){return context},getBoundingClientRect(){return {width:600,height:190,left:0}}});}
const buttons=['timeline','evidence','experiment'].map(p=>{const b=element('tab-'+p);b.dataset.page=p;return b;});
global.document={getElementById:element,createElement:()=>element('generated-'+Object.keys(elements).length),querySelectorAll:()=>buttons};
global.window={devicePixelRatio:1,addEventListener:()=>{}};
element('report-data').textContent=JSON.stringify(input.data);
eval(input.script);
element('from').value=25;element('from').oninput();assert(element('from-label').textContent.includes('s'));
buttons[1].onclick();assert.strictEqual(element('page-timeline').hidden,true);
buttons[0].onclick();assert.strictEqual(element('page-timeline').hidden,false);
assert(element('issues').children.length>0);assert(element('experiment').children.length>0);
console.log('offline report interactions passed');
'''
        result=subprocess.run(['node','-e',harness],input=json.dumps({'data':data,'script':script}),text=True,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
