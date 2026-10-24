"""Phase 4, AP 4.1: Rechenkern für lxc.idmap, subuid/subgid und gemeinsame Nummern."""
import pytest

from app.pve import mapping as M

# So ist der Test-Container 9005 (eigenes Mapping) von Hand eingerichtet
LINES_9005 = ['lxc.idmap: u 0 100000 1000', 'lxc.idmap: u 1000 1000 1', 'lxc.idmap: u 1001 101001 64535',
              'lxc.idmap: g 0 100000 1000', 'lxc.idmap: g 1000 1000 1', 'lxc.idmap: g 1001 101001 64535']


def test_eine_nummer_wie_9005():
    assert M.idmap_text([1000], [1000]) == LINES_9005


def test_benutzer_und_gruppe_verschieden():
    lines = M.idmap_text([1000], [2000])
    assert 'lxc.idmap: u 1000 1000 1' in lines and 'lxc.idmap: g 2000 2000 1' in lines
    assert 'lxc.idmap: g 0 100000 2000' in lines and 'lxc.idmap: g 2001 102001 63535' in lines


def test_mehrere_und_zusammenhaengende_nummern():
    r = M.plan_ranges([1000, 1001, 2000])
    assert r == [{'ct': 0, 'host': 100000, 'count': 1000}, {'ct': 1000, 'host': 1000, 'count': 2},
                 {'ct': 1002, 'host': 101002, 'count': 998}, {'ct': 2000, 'host': 2000, 'count': 1},
                 {'ct': 2001, 'host': 102001, 'count': 63535}]


@pytest.mark.parametrize('ids', [[[0]], [[65534]], [[65535]], [[70000]]])
def test_verbotene_nummern(ids):
    with pytest.raises(ValueError):
        M.plan_ranges(*ids)


@pytest.mark.parametrize('ids', [[1], [1000], [65533], [1, 2, 3], [5, 1000, 65533]])
def test_immer_lueckenlos(ids):
    r = M.plan_ranges(ids)
    assert r[0]['ct'] == 0 and sum(x['count'] for x in r) == 65536
    for a, b in zip(r, r[1:]):
        assert a['ct'] + a['count'] == b['ct']
    assert all(x['ct'] == x['host'] for x in r if x['ct'] in ids)


def test_ohne_nummern_wie_proxmox():
    assert M.plan_ranges([]) == M.DEFAULT


SUB = [{'user': 'root', 'start': 100000, 'count': 65536}, {'user': 'luro', 'start': 165536, 'count': 65536}]


def test_subuid_fehlt_nur_die_durchgereichte_nummer():
    assert M.subid_missing(M.plan_ranges([1000]), SUB) == ['root:1000:1']
    assert M.subid_missing(M.plan_ranges([1000]), SUB + [{'user': 'root', 'start': 1000, 'count': 1}]) == []
    assert M.subid_missing(M.plan_ranges([1000, 1001]), SUB) == ['root:1000:2']


def test_subuid_ganz_leer():
    assert M.subid_missing(M.plan_ranges([1000]), []) == ['root:1000:1', 'root:100000:65536']


def test_wer_teilt_die_nummer():
    scan = {'guests': [
        {'vmid': 9001, 'name': 'priv', 'type': 'lxc', 'config': {'unprivileged': False}},
        {'vmid': 9002, 'name': 'std', 'type': 'lxc', 'config': {'unprivileged': True}},
        {'vmid': 9005, 'name': 'idmap', 'type': 'lxc', 'config': {'unprivileged': True, 'idmap': [
            {'kind': 'u', 'ct': 0, 'host': 100000, 'count': 1000}, {'kind': 'u', 'ct': 1000, 'host': 1000, 'count': 1},
            {'kind': 'u', 'ct': 1001, 'host': 101001, 'count': 64535}]}},
        {'vmid': 106, 'name': 'vm', 'type': 'qemu'}]}
    hits = M.shared_with(scan, 'u', [1000])
    assert {(h['vmid'], h['privileged']) for h in hits} == {(9001, True), (9005, False)}
