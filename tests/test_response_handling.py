import json
import io
from urllib.error import HTTPError, URLError
from unittest import mock

from support import ROOT, FIXTURES, OfflineTest, envelope


class ResponseTests(OfflineTest):
    def test_http_error_classes(self):
        from it_access.providers import http_transport,ProviderError
        for status,retryable in [(429,True),(503,True),(401,False)]:
            body=io.BytesIO(b'SENTINEL-ERROR-BODY')
            error=HTTPError('https://example.invalid',status,'error',{},body)
            with mock.patch('it_access.providers.urlopen',side_effect=error),self.assertRaises(ProviderError) as caught:
                http_transport('https://example.invalid',{}, {'Authorization':'Bearer fake'},1)
            self.assertEqual(caught.exception.retryable,retryable)
            self.assertEqual(caught.exception.code,f'http_{status}')
            self.assertNotIn('SENTINEL',str(caught.exception))
            self.assertEqual(body.tell(),0)
        with mock.patch('it_access.providers.urlopen',side_effect=URLError('simulated')),self.assertRaises(ProviderError) as caught:
            http_transport('https://example.invalid',{}, {},1)
        self.assertTrue(caught.exception.retryable)

    def source(self):
        from it_access.core import load_source
        return load_source(ROOT/'materials/requests/IT-001.json')

    def failure(self, name):
        from it_access.pipeline import process
        from it_access.providers import MockProvider
        provider=MockProvider(fixture_dir=FIXTURES)
        provider.complete=mock.Mock(return_value=__import__('it_access.providers',fromlist=['ProviderReply']).ProviderReply(envelope(name),'mock'))
        result=process(self.source(),provider)
        self.assertEqual((result['status'],result['owner'],result['next_action']),('error','IT Service Desk','retry-extraction'))
        self.assertIsNone(result['extraction'])
        self.assertTrue(result['error'])

    def test_provider_failure(self):
        from it_access.pipeline import process
        from it_access.providers import MockProvider
        provider=MockProvider(fixture_dir=FIXTURES, before_response=lambda name: (_ for _ in ()).throw(TimeoutError('simulated')))
        self.assertEqual(process(self.source(),provider)['status'],'error')

    def test_refusal_response(self):
        self.failure('refusal.json')

    def test_interrupted_response(self):
        self.failure('interrupted.json')

    def test_malformed_output(self):
        self.failure('malformed.json')
        from it_access.pipeline import process
        from it_access.providers import MockProvider, ProviderReply
        for content in ['{', '{"request_id":"a","request_id":"b"}', 'null', '[]']:
            value=envelope();value['choices'][0]['message']['content']=content
            provider=MockProvider(fixture_dir=FIXTURES)
            provider.complete=mock.Mock(return_value=ProviderReply(value,'mock'))
            self.assertEqual(process(self.source(),provider)['status'],'error')

    def test_provider_configuration_and_redaction(self):
        from it_access.providers import OpenAIProvider
        captured=[]
        credential=mock.Mock(return_value='SENTINEL-NOT-A-REAL-KEY')
        def transport(url,payload,headers,timeout):
            captured.append((url,payload,headers,timeout))
            result=envelope();result['model']='configured-model'
            return result
        provider=OpenAIProvider(model='configured-model',credential_supplier=credential,transport=transport)
        reply=provider.complete(message=self.source().message)
        self.assertEqual(reply.response_source,'openai:configured-model')
        credential.assert_called_once_with()
        self.assertEqual(captured[0][1]['model'],'configured-model')
        self.assertEqual(captured[0][1]['messages'][-1]['content'],self.source().message)
        self.assertTrue(captured[0][1]['response_format']['json_schema']['strict'])
        from it_access.pipeline import process
        provider.transport=mock.Mock(side_effect=RuntimeError('SENTINEL-NOT-A-REAL-KEY'))
        failed=process(self.source(),provider)
        self.assertNotIn('SENTINEL',json.dumps(failed))
