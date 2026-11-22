from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import scripts.diagnosticar_gmail as diagnostic


@pytest.mark.parametrize('label', ['ALL', 'INBOX'])
def test_diagnostic_maps_all_to_include_spam_not_label(settings, tmp_path, monkeypatch, label):
    settings = replace(settings, root=tmp_path, gmail_label=label, gmail_campaign_tag='RPA-TEST-example')
    (tmp_path/'docs/evidence').mkdir(parents=True)
    monkeypatch.setattr(diagnostic, 'client_config', lambda _: {})
    monkeypatch.setattr(diagnostic, 'authorize', lambda *args: SimpleNamespace(token='fake'))
    monkeypatch.setattr(diagnostic, 'AuthorizedHttp', lambda *args, **kwargs: object())
    service = Mock()
    listing = service.users.return_value.messages.return_value.list
    listing.return_value.execute.return_value = {'messages': [{'id':'fixture'}]}
    monkeypatch.setattr(diagnostic, 'build', lambda *args, **kwargs: service)
    result = diagnostic.diagnose(settings)
    params = listing.call_args.kwargs
    assert params['userId']=='me' and params['maxResults']==1
    assert 'subject:"RPA-TEST-example"' in params['q'] and ' before:' in params['q']
    if label=='ALL':
        assert params['includeSpamTrash'] is True and 'labelIds' not in params
    else:
        assert params['labelIds']==['INBOX'] and 'includeSpamTrash' not in params
    listing.return_value.execute.assert_called_once_with(num_retries=0)
    service.close.assert_called_once()
    assert result['send_requests']==0
    assert result['roles']['receptor']['status']=='PROBADO_REAL'
