import unittest,tempfile,concurrent.futures,json
from pathlib import Path
import bounded_trace
class AtomicWriteTests(unittest.TestCase):
 def test_independent_process_writers_do_not_share_a_temporary_path(self):
  import subprocess,sys
  with tempfile.TemporaryDirectory() as directory:
   target=Path(directory)/'shared.json';script='import sys;sys.path.insert(0,sys.argv[1]);import bounded_trace;[bounded_trace.write(sys.argv[2],{"writer":sys.argv[3],"n":n}) for n in range(30)]'
   module=str(Path(bounded_trace.__file__).parent);processes=[subprocess.Popen([sys.executable,'-c',script,module,str(target),str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for i in range(4)]
   results=[(process,process.communicate()) for process in processes]
   for process,(out,err) in results:self.assertEqual(process.returncode,0,err.decode())
   self.assertEqual(json.loads(target.read_text())['n'],29);self.assertFalse(list(Path(directory).glob('*.tmp')))
