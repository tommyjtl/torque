"""Plain-language capability plumbing, automatic policy and retained output semantics."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'packages/device/src'),str(ROOT/'packages/session/src')]
from torque.device import Device
from torque.daemon import Daemon
from torque import policy
from unoq_control import Frame


class FakeBoard:
    def __init__(self):
        self.boot=123
        self.draws=[]
        self.frame=Frame((0,)*104)
        self.clips={}
        self.matrix=type('Matrix',(),{
            'draw':lambda _,frame:self.draw(frame),
            'load':lambda _,frames,durations:setattr(self,'loaded',frames),
            'cache':lambda _,slot:self.clips.update({slot:self.loaded}),
            'play_cached':lambda _,slot,repeat:self.draw(self.clips[slot][0])})()
    def draw(self,frame):
        self.frame=frame;self.draws.append(frame.to_hex())
    def snapshot(self):
        return {'boot_id':self.boot,'matrix':{'frame_hex':self.frame.to_hex(),'bits':self.frame.bits,'playing':False,
                'rows':[''.join('#' if p else '.' for p in self.frame.pixels[i*13:(i+1)*13]) for i in range(8)]},'rgb':{}}
    def info(self):return {'boot_id':self.boot,'version':'0.2.0','protocol':[1,1],'ready':True}
    def capability(self,name):return {'rows':8,'columns':13} if name=='matrix' else {'ids':[3,4]}


class RetainedTests(unittest.TestCase):
    def device(self,path=None,board=None):
        device=Device(ROOT/'assets/status.json',lambda value:None,path)
        device.board=board or FakeBoard();device.error=None
        return device
    def test_on_and_off_survive_session_feedback_changes(self):
        device=self.device()
        result=device.action('matrix_fill',{'on':True})
        self.assertEqual(result['lit_pixels'],104)
        for state in ('waiting','working','standby','error'):
            device.set_state(state);device.render()
        self.assertEqual(device.board.frame.to_hex(),'ff'*13)
        self.assertEqual(device.status()['display_mode'],'user')
        result=device.action('matrix_clear',{})
        device.set_state('standby');device.render()
        self.assertEqual(result['lit_pixels'],0)
        self.assertEqual(device.board.frame.to_hex(),'00'*13)
        self.assertTrue(result['retained'])
    def test_explicit_release_restores_status_and_program_takes_ownership(self):
        device=self.device();device.action('matrix_fill',{'on':True})
        device.action('matrix_release',{})
        self.assertEqual(device.status()['display_mode'],'status')
        self.assertNotEqual(device.board.frame.to_hex(),'ff'*13)
        device.action('matrix_fill',{'on':True});device.request('program','acquire',{})
        self.assertIsNone(device.intent)
        with self.assertRaisesRegex(RuntimeError,'owns'):
            device.action('matrix_clear',{})
        device.release('program');device.render()
        self.assertEqual(device.status()['display_mode'],'status')
    def test_restart_adopts_matching_state_without_replaying_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'display.json';board=FakeBoard()
            device=self.device(path,board);device.action('matrix_fill',{'on':False})
            count=len(board.draws)
            restarted=self.device(path,board);restarted.reconcile_intent(board.snapshot())
            restarted.set_state('working');restarted.render()
            self.assertEqual(len(board.draws),count)
            self.assertEqual(restarted.status()['display_mode'],'user')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
    def test_new_boot_or_changed_frame_invalidates_saved_intent_without_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'display.json';board=FakeBoard()
            device=self.device(path,board);device.action('matrix_fill',{'on':True})
            count=len(board.draws);board.boot+=1
            restarted=self.device(path,board);restarted.reconcile_intent(board.snapshot())
            self.assertIsNone(restarted.intent)
            self.assertFalse(path.exists())
            self.assertEqual(len(board.draws),count)
    def test_bad_frame_or_boolean_has_no_device_effect(self):
        device=self.device()
        for name,args in [('matrix_fill',{'on':1}),('matrix_draw',{'rows':['#'*12]*8})]:
            with self.assertRaises(ValueError):device.action(name,args)
        self.assertEqual(device.board.draws,[])


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);workspace=self.root/'workspace';(workspace/'projects').mkdir(parents=True)
        key=self.root/'credential';key.write_text('PRIVATE-FIXTURE-TORQUE');key.chmod(0o600)
        class Backend:
            def __init__(self,*args):self.calls=[]
            def status(self):return {'ready':True,'snapshot':None}
            def set_state(self,state):pass
            def action(self,name,args):self.calls.append((name,args));return {'lit_pixels':104,'retained':True}
        self.daemon=Daemon({'release_root':str(ROOT),'workspace':str(workspace),'state_dir':str(self.root/'state'),
            'key_file':str(key),'python':sys.executable,'socket':str(self.root/'socket'),'model':'fixture'},device_factory=Backend)
        self.daemon.engine_send=AsyncMock()
        self.daemon.worker=type('Worker',(),{'returncode':None})()
    async def test_default_auto_board_action_has_no_approval_and_validates_arguments(self):
        event={'request_id':'call','session_id':'session','tool':'matrix_fill','arguments':{'on':True}}
        await self.daemon.tool(event)
        self.assertEqual(self.daemon.device.calls,[('matrix_fill',{'on':True})])
        self.assertEqual(self.daemon.pending,{})
        self.assertFalse(any(e['type']=='approval.required' for e in self.daemon.events))
        event['arguments']={'on':'yes'}
        await self.daemon.tool(event)
        self.assertEqual(len(self.daemon.device.calls),1)
        self.assertEqual(self.daemon.engine_send.call_args.args[0]['result']['outcome'],'denied')
    async def test_ask_denial_prevents_the_same_board_effect(self):
        self.daemon.turn_permissions='ask'
        event={'request_id':'call','session_id':'session','tool':'matrix_fill','arguments':{'on':True}}
        task=asyncio.create_task(self.daemon.tool(event));await asyncio.sleep(0)
        await self.daemon.request('client',{'v':1,'op':'approve','request_id':'call','session_id':'session','allow':False})
        await task
        self.assertEqual(self.daemon.device.calls,[])
    async def test_auto_workspace_program_runs_without_shell_or_secret_env(self):
        path=self.daemon.workspace/'projects/demo.py'
        await self.daemon.tool({'request_id':'write','session_id':'s','tool':'write_file',
            'arguments':{'path':'projects/demo.py','content':'import os;print(os.environ.get("MODULAR_API_KEY","unset"))'}})
        await self.daemon.tool({'request_id':'run','session_id':'s','tool':'run_program','arguments':{'path':str(path),'arguments':[]}})
        result=self.daemon.engine_send.call_args.args[0]['result']
        self.assertEqual(result['value']['output'].strip(),'unset')
        self.assertFalse(self.daemon.pending)
        with self.assertRaises(ValueError):
            await self.daemon.execute('run_program',{'path':'../outside.py','arguments':[]})
    async def test_full_policy_is_not_the_default_and_readonly_tools_are_bounded(self):
        self.assertEqual(self.daemon.default_permissions,'auto')
        self.assertTrue(policy.needs_approval('shell','auto'))
        self.assertTrue(policy.needs_approval('write_file','ask'))
        self.assertFalse(policy.needs_approval('matrix_fill','auto'))
        self.assertFalse(policy.needs_approval('shell','full'))
        with self.assertRaises(ValueError):policy.mode('unrestricted')
        (self.daemon.workspace/'projects/example.py').write_text('needle\n')
        result=await self.daemon.execute('search_files',{'path':'projects','query':'needle'})
        self.assertEqual(result['matches'][0]['line'],1)
        with self.assertRaises(ValueError):await self.daemon.execute('list_directory',{'path':'/etc'})
    async def test_permission_choice_is_validated_and_default_does_not_leak(self):
        self.daemon.start_engine=AsyncMock()
        await self.daemon.request('client',{'v':1,'op':'prompt','prompt':'first','permissions':'full'})
        self.assertEqual(self.daemon.turn_permissions,'full')
        self.daemon.turn_active=False
        await self.daemon.request('client',{'v':1,'op':'prompt','prompt':'next'})
        self.assertEqual(self.daemon.turn_permissions,'auto')
        self.daemon.turn_active=False
        with self.assertRaises(ValueError):
            await self.daemon.request('client',{'v':1,'op':'prompt','prompt':'bad','permissions':'unrestricted'})
