import ctypes,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_launcher import Keychain
class KeychainTests(unittest.TestCase):
    def test_locked_read_does_not_wait_for_dialog_and_restores_interaction(self):
        calls=[];key=Keychain.__new__(Keychain)
        def previous(pointer):pointer._obj.value=True;return 0
        key.api=SimpleNamespace(SecKeychainGetUserInteractionAllowed=previous,
            SecKeychainSetUserInteractionAllowed=lambda allowed:calls.append(allowed) or 0)
        key._find=lambda _: (-25308,ctypes.c_uint32(),ctypes.c_void_p(),ctypes.c_void_p())
        with self.assertRaises(RuntimeError):key.get('fixture')
        self.assertEqual(calls,[False,True])
if __name__=='__main__':unittest.main()
