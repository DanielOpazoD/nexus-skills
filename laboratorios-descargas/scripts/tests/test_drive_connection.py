import base64,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs,urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import drive_oauth as oauth
from test_regression_workflow import Keychain
class DriveConnectionTests(unittest.TestCase):
    def test_refresh_cached_then_renewed_and_not_logged(self):
        key=Keychain();key.put(oauth.SERVICE,json.dumps({'client_id':'fixture','refresh_token':'refresh-secret'}));calls=[];clock=[100]
        def transport(values):calls.append(values);return {'access_token':'access-secret','expires_in':120}
        provider=oauth.DriveTokenProvider(key,transport,lambda:clock[0])
        self.assertEqual(provider(),'access-secret');self.assertEqual(provider(),'access-secret');self.assertEqual(len(calls),1)
        clock[0]=161;provider();self.assertEqual(len(calls),2);self.assertNotIn('access-secret',json.dumps(key.values))
    def test_revoked_auth_has_bounded_retry_and_generic_error(self):
        key=Keychain();key.put(oauth.SERVICE,json.dumps({'client_id':'fixture','refresh_token':'refresh-secret'}));calls=[]
        def transport(values):calls.append(values);raise ValueError('refresh-secret')
        provider=oauth.DriveTokenProvider(key,transport,lambda:100)
        for _ in range(3):
            with self.assertRaises(oauth.ConnectionRequired) as error:provider()
            self.assertNotIn('refresh-secret',str(error.exception))
        self.assertEqual(len(calls),1)
    def test_pkce_state_and_scoped_keychain_connection(self):
        key=Keychain();opened=[];exchanged=[];responses=[]
        class Server:
            server_port=12345
            def __init__(self,address,handler):self.handler=handler;self.n=0
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def handle_request(self):
                self.n+=1;query=parse_qs(urlsplit(opened[0]).query)
                obj=self.handler.__new__(self.handler);obj.path='/?'+urlencode({'state':'wrong' if self.n==1 else query['state'][0],'code':'authorization-secret'})
                obj.wfile=io.BytesIO();obj.send_response=responses.append;obj.send_header=lambda *a:None;obj.end_headers=lambda:None;obj.do_GET()
        def exchange(values):
            exchanged.append(values);query=parse_qs(urlsplit(opened[0]).query)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(values['code_verifier'].encode()).digest()).rstrip(b'=').decode()
            self.assertEqual(query['code_challenge'],[challenge]);self.assertEqual(query['scope'],[oauth.SCOPE]);self.assertEqual(values['redirect_uri'],'http://127.0.0.1:12345/')
            return {'refresh_token':'refresh-secret','scope':oauth.SCOPE}
        with tempfile.TemporaryDirectory() as out,patch.object(oauth,'HTTPServer',Server):
            config=Path(out)/'client.json';config.write_text(json.dumps({'installed':{'client_id':'fixture.apps.googleusercontent.com'}}))
            oauth.connect(config,key,opened.append,exchange)
        self.assertEqual(responses,[400,200]);self.assertEqual(len(exchanged),1);self.assertIn(oauth.SERVICE,key.values)
        self.assertNotIn('authorization-secret',json.dumps(key.values))
if __name__=='__main__':unittest.main()
