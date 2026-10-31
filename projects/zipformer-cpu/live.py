"""One matrix-guided local CPU voice trial; PCM/transcript text are not saved."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import struct
import subprocess
import threading
import time
import wave
from common import guide_rows, score

ROOT=Path(__file__).resolve().parent
EXPERIMENT=ROOT.parent/'ncnn-speech-benchmark'


class Worker:
    def __init__(self, output, decoder='greedy_search'):
        from torque.runtime import process_lease
        self.responses=queue.Queue(maxsize=4)
        self.log=(output/'worker.stderr.log').open('w')
        model_root=ROOT if (ROOT/'model-lock.json').exists() else EXPERIMENT
        model=json.loads((model_root/'model-lock.json').read_text())
        for name,info in model['files'].items():
            if hashlib.sha256((model_root/'models'/name).read_bytes()).hexdigest()!=info['sha256']:
                raise ValueError('Pinned model changed')
        env={k:v for k,v in os.environ.items() if not k.endswith(('_API_KEY','_TOKEN','_SECRET','_PASSWORD'))
             and k not in ('LD_LIBRARY_PATH','VULKAN_SDK')}
        env.update(TORQUE_NCNN_PROFILE='0',OMP_NUM_THREADS='4')
        with process_lease(live=True) as descriptors:
            self.process=subprocess.Popen([str(ROOT/'runtime/zipformer-live-worker'),str(model_root/'models'),decoder],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1,
                env=env,pass_fds=descriptors)
        def read():
            try:
                while line:=self.process.stdout.readline(65537):
                    if len(line)>65536:raise ValueError('Oversized worker reply')
                    self.responses.put(json.loads(line),timeout=2)
                self.responses.put({'error':'CPU worker ended'},timeout=2)
            except Exception as error:
                self.responses.put({'error':str(error)},timeout=2)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:
            self.ready=self.receive(20)
            if self.ready.get('execution_device')!='cpu':raise RuntimeError('CPU worker required')
        except BaseException:
            self.close();raise

    def receive(self, timeout=5):
        result=self.responses.get(timeout=timeout)
        if 'error' in result:raise RuntimeError(result['error'])
        return result

    def call(self,op,**values):
        self.process.stdin.write(json.dumps({'op':op,**values})+'\n');self.process.stdin.flush()
        return self.receive()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(3)
        for stream in (self.process.stdin,self.process.stdout,self.log):stream.close()


def selftest(worker):
    root=ROOT if (ROOT/'fixtures.json').exists() else EXPERIMENT
    clip=json.loads((root/'fixtures.json').read_text())['clips'][0]
    path=root/clip['path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==clip['sha256']
    with wave.open(str(path),'rb') as wav:
        assert wav.getparams()[:3]==(1,2,16000)
        raw=wav.readframes(wav.getnframes())
    pcm=[x/32768 for x, in struct.iter_unpack('<h',raw)]
    results=[]
    for rate in (16000,48000):
        worker.call('begin',rate=rate)
        samples=pcm if rate==16000 else [value for value in pcm for _ in range(3)]
        samples+= [0.]*(3*rate)
        block=rate//50
        for start in range(0,len(samples),block):worker.call('audio',samples=samples[start:start+block])
        state=worker.call('finish');quality=score(clip['reference'],state.pop('text'))
        assert quality['exact'] and state['natural_final_proven']
        results.append({'rate':rate,'exact_reference':True,'natural_final':True})
    print(json.dumps({'selftest_passed':True,'checks':results}),flush=True)
    return results


def capture(worker,output,*,free_speech=False):
    from torque import Board,Frame
    from torque.audio import Microphone,audio_capabilities
    from torque._audio_worker import Alsa,ROUTE
    caps=audio_capabilities()
    if not caps['available']:raise RuntimeError(caps['reason'])
    source=next(s for s in caps['sources'] if s['accessible'])
    alsa=Alsa(source['card'],source['card_index']);alsa.idle()
    controls={name:alsa.get(name) for name,_ in ROUTE}
    prompt='Show the heart animation'
    worker.call('begin',rate=48000)
    packets=queue.Queue(maxsize=50);stop=threading.Event();reader=None
    state={};frames=0;squares=0.;total=0.;clipped=0;peak=0.;max_lag=0.;first_arrival=None;ready=None
    print('LOCAL_CAPTURE_STARTING: up to 40 seconds, audio stays in memory. Wait for the matrix circle.',flush=True)
    with Board() as display:
        def show(name):display.matrix.draw(Frame.from_rows(guide_rows(name)))
        try:
            with Microphone(card=source['card'],seconds=40) as mic:
                for _ in range(25):mic.read(frames=960,latest=False)
                for digit in ('3','2','1'):
                    show(digit);until=time.monotonic()+1
                    while time.monotonic()<until:mic.read(frames=960,latest=False)
                show('speak');ready=time.monotonic()
                print('MICROPHONE_READY: '+('say one short English sentence, then pause.' if free_speech else
                      'say "Show the heart animation", then pause.'),flush=True)
                def drain():
                    try:
                        while not stop.is_set():
                            chunk=mic.read(frames=960,latest=False)
                            if chunk is None:break
                            packets.put((time.monotonic(),chunk),timeout=.2)
                    except Exception as error:
                        try:packets.put(error,timeout=.2)
                        except queue.Full:pass
                        stop.set()
                reader=threading.Thread(target=drain,daemon=True);reader.start()
                last=''
                while time.monotonic()-ready<30:
                    packet=packets.get(timeout=3)
                    if isinstance(packet,Exception):raise packet
                    arrival,chunk=packet
                    if first_arrival is None:first_arrival=arrival
                    lag=time.monotonic()-arrival;max_lag=max(max_lag,lag)
                    if lag>1:raise RuntimeError('Inference is more than one second behind capture')
                    samples=[x/2147483648 for x, in struct.iter_unpack('<i',chunk.pcm)]
                    frames+=len(samples);squares+=sum(x*x for x in samples);total+=sum(samples)
                    clipped+=sum(abs(x)>=.99999 for x in samples);peak=max(peak,max(abs(x) for x in samples))
                    state=worker.call('audio',samples=samples)
                    if state['text'] and state['text']!=last:
                        last=state['text'];print('PARTIAL: '+last.strip(),flush=True)
                    if state['natural_final_proven']:break
                stop.set();reader.join(3)
                if reader.is_alive():raise RuntimeError('Capture reader did not stop')
            cleaned=time.monotonic()
            assert controls=={name:alsa.get(name) for name,_ in ROUTE},'Mixer restoration mismatch'
            show('working');state=worker.call('finish');text=state.pop('text').strip()
            print('FINAL: '+(text or '[no speech]'),flush=True)
            show('done');time.sleep(2)
        finally:
            stop.set()
            if reader:reader.join(3)
            display.close()
    saved={**state,'prompt_id':'free-speech' if free_speech else 'heart-animation',
        'score':None if free_speech else score(prompt,text),'accuracy_validated':False,'input_frames_48000':frames,
        'input_rms':(squares/frames)**.5 if frames else 0,'input_peak':peak,'max_queue_lag_seconds':max_lag,
        'input_mean':total/frames if frames else 0,'clipped_sample_fraction':clipped/frames if frames else 0,
        'ready_monotonic':ready,'first_pcm_arrival_monotonic':first_arrival,'capture_cleanup_monotonic':cleaned,
        'mixer_restored':True,'audio_saved':False,'transcript_saved':False,'execution_device':'cpu',
        'reference_speech_end_latency':None,'timing_note':'No independent human speech-end annotation; short single-phrase trial only'}
    (output/'metrics.json').write_text(json.dumps(saved,indent=2)+'\n')
    print('MICROPHONE_CLOSED; matrix ownership released.',flush=True)
    return saved


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--selftest',action='store_true')
    parser.add_argument('--free-speech',action='store_true',help='No expected phrase or automatic accuracy score')
    parser.add_argument('--decoder',choices=('greedy_search','modified_beam_search'),default='greedy_search')
    args=parser.parse_args()
    from torque.protocol import Connection
    with Connection() as client:before=client.request('status')
    if before['active'] or before['pending'] or before['maintenance'] or before['device']['owner']:
        raise RuntimeError('Torque is busy; no other work was cancelled')
    output=ROOT/'results'/(time.strftime('%Y%m%dT%H%M%S')+('-selftest' if args.selftest else '-voice'))
    output.mkdir(parents=True,mode=0o700)
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    worker=None
    try:
        worker=Worker(output,args.decoder)
        result=selftest(worker) if args.selftest else capture(worker,output,free_speech=args.free_speech)
        with Connection() as client:after=client.request('status')
        assert all(before[k]==after[k] for k in ('release_id','epoch'))
        assert before['device']['snapshot']['boot_id']==after['device']['snapshot']['boot_id']
        (output/'completed.json').write_text(json.dumps({'completed':True,'runtime_and_firmware_preserved':True,'selftest':args.selftest}))
        print('RESULT_DIRECTORY: '+str(output),flush=True)
    finally:
        if worker:worker.close()


if __name__=='__main__':main()
