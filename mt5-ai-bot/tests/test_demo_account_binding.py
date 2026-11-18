import json
from types import SimpleNamespace

import pytest

from src.execution.demo_account_binding import AccountBindingError,create_local_binding,verify_local_binding


class FakeApi:
    ACCOUNT_TRADE_MODE_DEMO=0
    def __init__(self, *, login=12345678, server="Broker-Demo", path=r"C:\\MT5", data=r"C:\\MT5Data", mode=0):
        self.login,self.server,self.path,self.data,self.mode=login,server,path,data,mode
    def terminal_info(self):return SimpleNamespace(path=self.path,data_path=self.data)
    def account_info(self):return SimpleNamespace(login=self.login,server=self.server,trade_mode=self.mode,password="NEVER")


def test_binding_is_local_hashed_and_detects_every_identity_switch(tmp_path):
    path=tmp_path/"binding.json";api=FakeApi()
    public=create_local_binding(api,path)
    assert public["account_label"]=="••••5678"
    raw=path.read_text()
    assert "12345678" not in raw and "C:\\\\MT5" not in raw and "NEVER" not in raw
    assert verify_local_binding(api,path)["verified"] is True
    for changed in (FakeApi(login=87654321),FakeApi(server="Other-Demo"),FakeApi(path=r"D:\\MT5"),FakeApi(data=r"D:\\Data")):
        with pytest.raises(AccountBindingError,match="changed"):
            verify_local_binding(changed,path)


def test_funded_binding_and_silent_repin_are_prohibited(tmp_path):
    path=tmp_path/"binding.json"
    with pytest.raises(AccountBindingError,match="DEMO"):
        create_local_binding(FakeApi(mode=2),path)
    create_local_binding(FakeApi(),path)
    with pytest.raises(AccountBindingError,match="replacement"):
        create_local_binding(FakeApi(),path)
