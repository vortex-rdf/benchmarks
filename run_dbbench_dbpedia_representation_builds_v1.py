#!/usr/bin/env python3
"""Build and measure DBpedia COTTAS, HDT, and current Vortex artifacts."""
from __future__ import annotations
import argparse, hashlib, importlib.metadata, json, os, platform, shlex, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_core.build_metrics import measure_representation_size, run_build_command
from benchmark_core.representation import create_inventory, create_receipt

BENCHMARKS = Path('/users/u0182905/benchmarks')
DBPEDIA = Path('/users/u0182905/DBPedia')
VORTEX_RDF = Path('/users/u0182905/vortex-rdf')
VORTEX_RDFLIB = Path('/users/u0182905/vortex-rdflib')
SOURCE = DBPEDIA / 'data/dbpedia_en_all.nt'
OUT = DBPEDIA / 'data/current-evaluation'
RDF2HDT = BENCHMARKS / 'BSBM/data/tools/rdf2hdt-0.2.0/bin/rdf2hdt'
VORTEX_CLI = VORTEX_RDF / 'target/release/vortex-rdf-cli'
HDT_PYTHON = Path(os.environ.get('KROWN_HDT_INDEX_PYTHON','/users/u0182905/KROWN/.runtime/rdflib-hdt-3.3/bin/python'))
SOURCE_SHA = '2a6949c60134a5d453c4b9d2723a7e04a710fdcf5c3ebb34ee3a7f04f262d4ba'
LEGACY = DBPEDIA / 'data/vortex_cottas_ids_v10/dbpedia_CNI_v10.vortex'
LEGACY_SHA = 'f2f69bc879f54a32f8062f58742b7a8b6d806ea13ae534c013b344965cd3b4c5'


def utc(): return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def sha(path):
 d=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): d.update(b)
 return d.hexdigest()
def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name('.'+path.name+'.tmp')
 tmp.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n'); tmp.replace(path)

def announce(message):
 print(f'[{utc()}] {message}',flush=True)
def read(path): return json.loads(path.read_text())
def file_record(path): return {'path':path.name,'size_bytes':path.stat().st_size,'sha256':sha(path)}

def stage_source():
 target = OUT/'dataset.nt'
 if target.exists():
  if not target.is_file() or target.stat().st_size!=SOURCE.stat().st_size or sha(target)!=SOURCE_SHA:
   raise RuntimeError('staged DBpedia source identity differs')
  return target
 try:
  os.link(SOURCE,target)
 except OSError as error:
  raise RuntimeError(
   'DBpedia source and current-evaluation must support a hard link; '
   'refusing to copy the 35.56 GB source'
  ) from error
 if sha(target)!=SOURCE_SHA:
  target.unlink(missing_ok=True)
  raise RuntimeError('staged DBpedia source hash differs')
 return target

def source_receipt(triples):
 staged=stage_source()
 p=OUT/'rdf-source-receipt.json'
 create_receipt(receipt_path=p,benchmark='dbbench',dataset='dbpedia-en-all',source_format='ntriples',source_path=staged,representation='rdf/source',files=[staged.name],producer={'kind':'DBpedia-testbed','source_path':str(SOURCE),'source_triple_count':triples},created_at_utc=utc())
 return p

def annotate(receipt,metrics,outputs):
 v=read(receipt); v['producer']['build_metrics']=metrics; v['producer']['representation_size']=measure_representation_size(outputs); atomic(receipt,v)
def stage(name,command,outputs,receipt,log,resume=False,cwd=BENCHMARKS,env=None,after=None,ledger=None,ledger_path=None):
 if resume and receipt.is_file() and all(p.is_file() for p in outputs):
  v=read(receipt); expected={x['path']:x for x in v['files']}
  if all(p.name in expected and p.stat().st_size==expected[p.name]['size_bytes'] and sha(p)==expected[p.name]['sha256'] for p in outputs):
   announce(f'STAGE RESUMED name={name}')
   return {'stage':name,'status':'resumed','representation_size':measure_representation_size(outputs)}
 for p in outputs: p.unlink(missing_ok=True)
 receipt.unlink(missing_ok=True)
 log.parent.mkdir(parents=True,exist_ok=True)
 if ledger is not None and ledger_path is not None:
  ledger['current_stage']={'name':name,'status':'running','started_at_utc':utc(),'command':command,'log':str(log),'outputs':[str(p) for p in outputs]}
  atomic(ledger_path,ledger)
 announce(f'STAGE START name={name}')
 announce('COMMAND '+shlex.join(command))
 announce(f'LOG {log}')
 announce('OUTPUTS '+', '.join(str(p) for p in outputs))
 metrics=run_build_command(command,cwd=cwd,environment=env,log_path=log)
 announce(f'STAGE COMMAND END name={name} status={metrics.get("status")} returncode={metrics.get("returncode")}')
 if metrics['status']!='ok': raise RuntimeError(f'{name} failed; see {log}')
 if after: after()
 if not receipt.is_file() or any(not p.is_file() or p.stat().st_size==0 for p in outputs): raise RuntimeError(f'{name} did not publish its complete bundle')
 annotate(receipt,metrics,outputs)
 result={'stage':name,'status':'ok','build_metrics':metrics,'representation_size':measure_representation_size(outputs),'outputs':[file_record(p) for p in outputs]}
 if ledger is not None:
  ledger.pop('current_stage',None)
 announce(f'STAGE COMPLETE name={name}')
 return result
def vortex_receipt(output,receipt,triples,index):
 create_receipt(receipt_path=receipt,benchmark='dbbench',dataset='dbpedia-en-all',source_format='ntriples',source_path=SOURCE,representation=f'vortex-rdf/dictionary-{index}',files=[output.name],producer={'kind':'vortex-rdf-cli','layout':'dictionary','index':index,'source_triple_count':triples,'binary_sha256':sha(VORTEX_CLI),'command':['vortex-rdf-cli','serialize','-i',SOURCE.name,'-o',output.name,'--indexes',index,'--layout','dictionary']},created_at_utc=utc())

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--triple-count',type=int,required=True); ap.add_argument('--resume',action='store_true'); ap.add_argument('--delete-legacy-v10',action='store_true'); ap.add_argument('--stage',choices=('all','hdt','cottas','vortex-reference','vortex-copy'),default='all'); a=ap.parse_args()
 if not SOURCE.is_file() or sha(SOURCE)!=SOURCE_SHA: raise RuntimeError('canonical DBpedia source identity differs')
 for p in (RDF2HDT,HDT_PYTHON):
  if not p.is_file(): raise FileNotFoundError(p)
 if importlib.metadata.version('pycottas')!='1.1.0': raise RuntimeError('pycottas 1.1.0 is required')
 OUT.mkdir(parents=True,exist_ok=True); logs=OUT/'build-logs'; logs.mkdir(exist_ok=True)
 ledger={'schema':'dbbench-representation-build-ledger-v1','benchmark':'dbbench','dataset':'dbpedia-en-all','started_at_utc':utc(),'status':'running','requested_stage':a.stage,'source':file_record(SOURCE),'stages':[]}
 ledger_path=OUT/'representation-build-ledger.json'; atomic(ledger_path,ledger)
 rdf=source_receipt(a.triple_count); inventory=OUT/'dataset-inventory.json'
 try:
  announce(f'BUILD PLAN requested_stage={a.stage}')
  hdt=OUT/'dataset.hdt'; hdt_index=OUT/'dataset.hdt.index.v1-1'; hdt_r=OUT/'hdt-default-receipt.json'
  if a.stage in ('all','hdt'):
   ledger['stages'].append(stage('hdt/default',[sys.executable,'-c','from pathlib import Path; from DBBench.representations import generate_hdt; import sys; generate_hdt(source=Path(sys.argv[1]),output=Path(sys.argv[2]),rdf_receipt=Path(sys.argv[3]),hdt_receipt=Path(sys.argv[4]),inventory=Path(sys.argv[5]),rdf2hdt=Path(sys.argv[6]),source_triple_count=int(sys.argv[7]))',str(SOURCE),str(hdt),str(rdf),str(hdt_r),str(inventory),str(RDF2HDT),str(a.triple_count)],[hdt,hdt_index],hdt_r,logs/'hdt.log',a.resume,env={**os.environ,'KROWN_HDT_INDEX_PYTHON':str(HDT_PYTHON)},ledger=ledger,ledger_path=ledger_path)); atomic(ledger_path,ledger)
  cottas=OUT/'dataset.cottas'; cottas_r=OUT/'cottas-default-receipt.json'
  if a.stage in ('all','cottas'):
   ledger['stages'].append(stage('cottas/default',[sys.executable,'-c','from pathlib import Path; from DBBench.representations import generate_cottas; import sys; generate_cottas(source=Path(sys.argv[1]),output=Path(sys.argv[2]),rdf_receipt=Path(sys.argv[3]),cottas_receipt=Path(sys.argv[4]),inventory=Path(sys.argv[5]),source_triple_count=int(sys.argv[6]))',str(SOURCE),str(cottas),str(rdf),str(cottas_r),str(inventory),str(a.triple_count)],[cottas],cottas_r,logs/'cottas.log',a.resume,ledger=ledger,ledger_path=ledger_path)); atomic(ledger_path,ledger)
  vortex_receipts=[]
  selected_indexes=[]
  if a.stage in ('all','vortex-reference'): selected_indexes.append('secondary-by-reference')
  if a.stage in ('all','vortex-copy'): selected_indexes.append('secondary-by-copy')
  if selected_indexes:
   announce('VORTEX CLI BUILD START reason=required-by-selected-vortex-stage')
   subprocess.run(['cargo','build','--release','-p','vortex-rdf-cli'],cwd=VORTEX_RDF,check=True)
   announce(f'VORTEX CLI BUILD COMPLETE binary={VORTEX_CLI}')
  for index in selected_indexes:
   output=OUT/f'dataset-dictionary-{index}.vortex'; receipt=OUT/f'vortex-rdf-dictionary-{index}-receipt.json'; vortex_receipts.append(receipt)
   cmd=[str(VORTEX_CLI),'serialize','-i',str(SOURCE),'-o',str(output),'--indexes',index,'--layout','dictionary']
   ledger['stages'].append(stage(f'vortex-rdf/dictionary-{index}',cmd,[output],receipt,logs/f'vortex-{index}.log',a.resume,cwd=VORTEX_RDF,env={**os.environ,'RUST_LOG':'vortex_rdf_cli=debug,vortex_rdf_core=debug'},after=lambda o=output,r=receipt,i=index:vortex_receipt(o,r,a.triple_count,i),ledger=ledger,ledger_path=ledger_path)); atomic(ledger_path,ledger)
  required_receipts=[rdf,hdt_r,cottas_r,OUT/'vortex-rdf-dictionary-secondary-by-reference-receipt.json',OUT/'vortex-rdf-dictionary-secondary-by-copy-receipt.json']
  if all(p.is_file() for p in required_receipts):
   create_inventory(inventory_path=inventory,benchmark='dbbench',dataset='dbpedia-en-all',receipt_paths=[p.name for p in required_receipts])
  elif a.stage=='all':
   raise RuntimeError('all-stage run ended without every required receipt')
  if a.stage=='all' and a.delete_legacy_v10 and LEGACY.exists():
   if sha(LEGACY)!=LEGACY_SHA: raise RuntimeError('legacy Vortex v10 hash differs; refusing deletion')
   LEGACY.unlink(); parent=LEGACY.parent
   if parent.is_dir() and not any(parent.iterdir()): parent.rmdir()
   ledger['legacy_v10_deleted']=str(LEGACY)
  ledger.pop('current_stage',None); ledger.update(status='ok',finished_at_utc=utc(),inventory=str(inventory) if inventory.is_file() else None,receipts=[str(p) for p in required_receipts if p.is_file()]); atomic(ledger_path,ledger)
  announce(f'BUILD COMPLETE requested_stage={a.stage}')
 except BaseException as e:
  if isinstance(ledger.get('current_stage'),dict): ledger['current_stage']['status']='failed'
  ledger.update(status='failed',finished_at_utc=utc(),error=f'{type(e).__name__}: {e}'); atomic(ledger_path,ledger); announce(f'BUILD FAILED error={type(e).__name__}: {e}'); raise
 print(ledger_path)
 return 0
if __name__=='__main__': raise SystemExit(main())
