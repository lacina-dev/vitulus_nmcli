#!/usr/bin/env python3
"""Offline tests of nodes/network_manager (T39): no ROS master, no D-Bus.

rospy, NetworkManager, dbus and vitulus_msgs are replaced by fakes before the node file is
loaded; the fake NetworkManager counts every D-Bus-like call.

    python3 test/test_network_manager.py
"""
import importlib.machinery
import importlib.util
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
NODE = os.path.join(os.path.dirname(HERE), "nodes", "network_manager")


# ---------------------------------------------------------------- fakes
class Msg(object):
    _fields = {}

    def __init__(self):
        self.header = types.SimpleNamespace(stamp=None)
        for k, v in self._fields.items():
            setattr(self, k, list(v) if isinstance(v, list) else v)


def msgtype(name, **fields):
    return type(name, (Msg,), {"_fields": fields})


NmConn = msgtype("NmConn", connections=[])
NmSsid = msgtype("NmSsid", ssid="", freq=0, signal=0)
NmSsidList = msgtype("NmSsidList", ssid_list=[], scan_time=None)
NmConnDetail = msgtype("NmConnDetail", status="", connection="", device="", mode="",
                       mac_address="", ssid="", signal="", freq="", key_mgmt="", psk="",
                       method="", addresses=[], routes=[], dns=[])
NmConnAdd = msgtype("NmConnAdd", ssid="", psk_password="")


class Pub(object):
    def __init__(self, name, cls, queue_size=None, latch=False):
        self.name, self.latch, self.sent = name, latch, []

    def publish(self, m):
        self.sent.append(m)


class Clock(object):
    t = 1000


def make_rospy():
    r = types.ModuleType("rospy")
    r.pubs = {}

    def publisher(name, cls, **kw):
        p = Pub(name, cls, **kw)
        r.pubs[name] = p
        return p
    r.Publisher = publisher
    r.Subscriber = lambda *a, **k: None
    r.get_param = lambda name, default=None: default
    r.Time = types.SimpleNamespace(now=lambda: Clock.t)
    r.get_caller_id = lambda: "/test"
    for n in ("loginfo", "logwarn", "logerr", "logwarn_throttle"):
        setattr(r, n, lambda *a, **k: None)
    r.ROSInterruptException = Exception
    return r


CALLS = []


class Obj(object):
    def __init__(self, path):
        self.object_path = path


class Ip4(Obj):
    def __init__(self, path, addr):
        Obj.__init__(self, path)
        self.Addresses = [[addr, 24, "192.168.0.254"]]
        self.Routes = []
        self.Nameservers = ["192.168.0.254"]


class Dev(object):
    def __init__(self, ip4):
        self.Interface = "wlp0s20f3"
        self.Ip4Config = ip4


class Conn(Obj):
    def __init__(self, path, cid, ctype="802-11-wireless"):
        Obj.__init__(self, path)
        self.cid, self.ctype = cid, ctype

    def GetSettings(self):
        CALLS.append("GetSettings")
        return {"connection": {"id": self.cid, "type": self.ctype},
                "802-11-wireless": {"ssid": self.cid, "mode": "infrastructure"},
                "802-11-wireless-security": {"key-mgmt": "wpa-psk"},
                "ipv4": {"method": "auto"}}

    def GetSecrets(self):
        CALLS.append("GetSecrets")
        return {"802-11-wireless-security": {"psk": "SECRET-PASSWORD"}}


class Active(Obj):
    def __init__(self, path, conn, ip4):
        Obj.__init__(self, path)
        self._state, self._ip4, self.Connection = 2, ip4, conn
        self._dev = Dev(ip4)

    @property
    def State(self):
        CALLS.append("State")
        return self._state

    @property
    def Ip4Config(self):
        CALLS.append("Ip4Config")
        return self._ip4

    @property
    def Devices(self):
        return [self._dev]


class FakeNM(object):
    def __init__(self):
        self.saved = [Conn("/S/1", "VitulusConnect"), Conn("/S/2", "Other"),
                      Conn("/S/3", "eth", "802-3-ethernet")]
        self.active = [Active("/A/1", self.saved[0], Ip4("/I/1", "192.168.0.40"))]

    @property
    def ActiveConnections(self):
        CALLS.append("ActiveConnections")
        return list(self.active)

    def GetDevices(self):
        return []


def load_node():
    fake = FakeNM()
    nm = types.ModuleType("NetworkManager")
    nm.const = None
    nm.NetworkManager = fake
    nm.Settings = types.SimpleNamespace(ListConnections=lambda: (CALLS.append("List"),
                                                                 list(fake.saved))[1])
    nm.NM_DEVICE_TYPE_WIFI = 2
    rospy = make_rospy()
    msgs = types.ModuleType("vitulus_msgs.msg")
    for c in (NmConn, NmSsid, NmSsidList, NmConnDetail, NmConnAdd):
        setattr(msgs, c.__name__, c)
    std = types.ModuleType("std_msgs.msg")
    std.Bool = std.String = std.Empty = lambda: types.SimpleNamespace(data=None)
    glib = types.ModuleType("dbus.mainloop.glib")
    glib.DBusGMainLoop = lambda **k: None
    mods = {"rospy": rospy, "NetworkManager": nm, "vitulus_msgs": types.ModuleType("vm"),
            "vitulus_msgs.msg": msgs, "std_msgs": types.ModuleType("std"),
            "std_msgs.msg": std, "dbus": types.ModuleType("dbus"),
            "dbus.mainloop": types.ModuleType("dbus.mainloop"),
            "dbus.mainloop.glib": glib}
    sys.modules.update(mods)
    loader = importlib.machinery.SourceFileLoader("nm_node_under_test", NODE)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.subprocess = types.SimpleNamespace(                     # the nmcli scan
        run=lambda *a, **k: types.SimpleNamespace(returncode=0))
    node = mod.NmcliNode()
    return mod, node, fake, rospy


class NodeTest(unittest.TestCase):
    def setUp(self):
        del CALLS[:]
        self.mod, self.node, self.nm, self.rospy = load_node()
        self.detail = self.rospy.pubs["conn_detail"]
        self.clist = self.rospy.pubs["conn_list"]
        self.ssids = self.rospy.pubs["ssid_list"]

    def run_s(self, n, t0=0.0):
        for i in range(n):
            Clock.t = t0 + i
            self.node.step(now=t0 + i)

    def test_launch_respawns_the_node(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(os.path.dirname(HERE), "launch", "nmcli.launch")).getroot()
        nodes = [n for n in root.iter("node") if n.get("type") == "network_manager"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].get("respawn"), "true")
        self.assertEqual(nodes[0].get("respawn_delay"), "30")

    def test_latched(self):
        self.assertTrue(self.detail.latch and self.clist.latch and self.ssids.latch)

    def test_no_secret_read_or_published(self):
        self.run_s(40)
        self.assertNotIn("GetSecrets", CALLS)
        self.assertTrue(all(m.psk == "" for m in self.detail.sent))
        self.assertEqual(self.detail.sent[-1].status, "Connected")
        self.assertEqual(self.detail.sent[-1].ssid, "VitulusConnect")
        self.assertEqual(self.detail.sent[-1].addresses, ["192.168.0.40/24 gw 192.168.0.254"])

    def test_detail_every_second_with_fresh_stamp(self):
        # device_state_publisher: wifi DISABLED when the stamp is older than 3 s
        self.run_s(20)
        self.assertEqual(len(self.detail.sent), 20)
        self.assertEqual(self.detail.sent[-1].header.stamp, 19)

    def test_few_dbus_calls_when_nothing_changes(self):
        self.run_s(1)
        del CALLS[:]
        self.run_s(14, t0=1)                      # inside one refresh period
        self.assertNotIn("GetSettings", CALLS)
        self.assertNotIn("List", CALLS)
        self.assertLessEqual(len(CALLS), 14 * 3)  # ActiveConnections + State + Ip4Config
        self.assertEqual(len(self.clist.sent), 1)  # conn_list: once, latched
        self.assertEqual(len(self.ssids.sent), 1)

    def test_periodic_full_read(self):
        self.run_s(31)
        self.assertEqual(CALLS.count("List"), 3)   # t=0, 15, 30
        self.assertEqual(len(self.clist.sent), 3)  # + heartbeat

    def test_change_is_seen_next_second(self):
        self.run_s(3)
        new = Ip4("/I/2", "192.168.0.41")                       # new DHCP lease
        self.nm.active[0]._ip4 = self.nm.active[0]._dev.Ip4Config = new
        Clock.t = 3
        self.node.step(now=3)
        self.assertEqual(self.detail.sent[-1].addresses, ["192.168.0.41/24 gw 192.168.0.254"])
        self.nm.active = []                                      # wifi gone
        self.node.step(now=4)
        self.assertEqual(self.detail.sent[-1].status, "Disconnected")

    def test_new_saved_connection_by_own_action(self):
        self.run_s(2)
        self.nm.saved.append(self.mod.NetworkManager.Settings.ListConnections()[0].__class__(
            "/S/9", "NewWifi"))
        self.node.add_connection = lambda ssid, pw: "ok"
        self.node.callback_conn_add(types.SimpleNamespace(ssid="NewWifi",
                                                          psk_password="12345678"))
        self.node.step(now=2)
        self.assertIn("NewWifi", self.clist.sent[-1].connections)
        self.assertEqual(len(self.clist.sent), 2)

    def test_dbus_error_does_not_kill_signature(self):
        self.run_s(1)

        def boom():
            raise RuntimeError("NM restarted")
        self.node.state_signature = boom
        self.assertTrue(self.node.needs_full_read(now=2))


if __name__ == "__main__":
    unittest.main()
