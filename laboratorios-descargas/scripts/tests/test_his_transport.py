import sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as l
from clinical_transport import tls_context
import ssl
his=l.load_backend('his')
from his_reports import http_client,auth
from his_reports.errors import HISError
class Tests(unittest.TestCase):
 def test_login_post_not_retried(self):
  with patch.object(http_client,'get_breaker',return_value=MagicMock()),patch.object(http_client,'_single_fetch',return_value=(503,{},b'')) as fetch,patch.object(http_client.time,'sleep') as sleep:
   status,_,_=http_client.fetch_his('/hishhr/acceso1.php',method='POST',data=b'fixture')
   self.assertEqual(status,503);self.assertEqual(fetch.call_count,1);sleep.assert_not_called()
 def test_long_retry_after_respected(self):
  with patch.object(http_client,'get_breaker',return_value=MagicMock()),patch.object(http_client,'_single_fetch',return_value=(503,{'Retry-After':'120'},b'')) as fetch,patch.object(http_client.time,'sleep') as sleep:
   status,_,_=http_client.fetch_his('/hishhr/')
   self.assertEqual(status,503);self.assertEqual(fetch.call_count,1);sleep.assert_not_called()
 def test_down_server_is_not_credentials_error(self):
  with patch.object(auth,'fetch_his',return_value=(503,{},b'')):
   with self.assertRaises(HISError) as e:auth.try_login('fixture','fixture')
   self.assertEqual(e.exception.status,503)
  with patch.object(his.socket,'create_connection'),patch.object(auth,'try_login',side_effect=HISError(503,'fixture')):
   with self.assertRaises(his.SiteUnavailable):his.HIS().login('fixture','fixture')
 def test_tls_keeps_validation(self):
  context=tls_context();self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED);self.assertTrue(context.check_hostname)
if __name__=='__main__':unittest.main()
