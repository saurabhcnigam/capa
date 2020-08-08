# Copyright (C) 2020 FireEye, Inc. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
# You may obtain a copy of the License at: [package root]/LICENSE.txt
# Unless required by applicable law or agreed to in writing, software distributed under the License
#  is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

import os.path
import collections

try:
    from functools import lru_cache
except ImportError:
    # pip install backports.functools-lru-cache
    from backports.functools_lru_cache import lru_cache

import pytest

import capa.features
import capa.features.file
import capa.features.insn
import capa.features.basicblock
import capa.features.extractors.lancelot.file
import capa.features.extractors.lancelot.insn
import capa.features.extractors.lancelot.function
import capa.features.extractors.lancelot.basicblock
from capa.features import ARCH_X32, ARCH_X64

CD = os.path.dirname(__file__)


@lru_cache
def extract_file_features(extractor):
    features = set([])
    for feature, va in extractor.extract_file_features():
        features.add(feature)
    return features


@lru_cache
def extract_function_features(extractor, f):
    features = collections.defaultdict(set)
    for bb in extractor.get_basic_blocks(f):
        for insn in extractor.get_instructions(f, bb):
            for feature, va in extractor.extract_insn_features(f, bb, insn):
                features[feature].add(va)
        for feature, va in extractor.extract_basic_block_features(f, bb):
            features[feature].add(va)
    for feature, va in extractor.extract_function_features(f):
        features[feature].add(va)
    return features


@lru_cache
def extract_basic_block_features(extractor, f, bb):
    features = set({})
    for insn in extractor.get_instructions(f, bb):
        for feature, _ in extractor.extract_insn_features(f, bb, insn):
            features.add(feature)
    for feature, _ in extractor.extract_basic_block_features(f, bb):
        features.add(feature)
    return features


@lru_cache
def get_lancelot_extractor(path):
    with open(path, "rb") as f:
        buf = f.read()

    return capa.features.extractors.lancelot.LancelotFeatureExtractor(buf)


@pytest.fixture
def sample(request):
    if request.param == "mimikatz":
        return os.path.join(CD, "data", "mimikatz.exe_")
    elif request.param == "kernel32":
        return os.path.join(CD, "data", "kernel32.dll_")
    elif request.param == "pma12-04":
        return os.path.join(CD, "data", "Practical Malware Analysis Lab 12-04.exe_")
    else:
        raise ValueError("unexpected sample fixture")


def get_function(extractor, fva):
    for f in extractor.get_functions():
        if f.__int__() == fva:
            return f
    raise ValueError("function not found")


def get_basic_block(extractor, f, va):
    for bb in extractor.get_basic_blocks(f):
        if bb.__int__() == va:
            return bb
    raise ValueError("basic block not found")


@pytest.fixture
def scope(request):
    if request.param == "file":
        return extract_file_features
    elif "bb=" in request.param:
        # like `function=0x401000,bb=0x40100A`
        fspec, _, bbspec = request.param.partition(",")
        fva = int(fspec.partition("=")[2], 0x10)
        bbva = int(bbspec.partition("=")[2], 0x10)

        def inner(extractor):
            f = get_function(extractor, fva)
            bb = get_basic_block(extractor, f, bbva)
            return extract_basic_block_features(extractor, f, bb)

        return inner
    elif request.param.startswith("function"):
        # like `function=0x401000`
        va = int(request.param.partition("=")[2], 0x10)

        def inner(extractor):
            f = get_function(extractor, va)
            return extract_function_features(extractor, f)

        return inner
    else:
        raise ValueError("unexpected scope fixture")


@pytest.mark.parametrize(
    "sample,scope,feature,expected",
    [
        # file/characteristic("embedded pe")
        ("pma12-04", "file", capa.features.Characteristic("embedded pe"), True),
        # file/string
        ("mimikatz", "file", capa.features.String("SCardControl"), True),
        ("mimikatz", "file", capa.features.String("SCardTransmit"), True),
        ("mimikatz", "file", capa.features.String("ACR  > "), True),
        ("mimikatz", "file", capa.features.String("nope"), False),
        # file/sections
        ("mimikatz", "file", capa.features.file.Section(".rsrc"), True),
        ("mimikatz", "file", capa.features.file.Section(".text"), True),
        ("mimikatz", "file", capa.features.file.Section(".nope"), False),
        # file/exports
        ("kernel32", "file", capa.features.file.Export("BaseThreadInitThunk"), True),
        ("kernel32", "file", capa.features.file.Export("lstrlenW"), True),
        ("kernel32", "file", capa.features.file.Export("nope"), False),
        # file/imports
        ("mimikatz", "file", capa.features.file.Import("advapi32.CryptSetHashParam"), True),
        ("mimikatz", "file", capa.features.file.Import("CryptSetHashParam"), True),
        ("mimikatz", "file", capa.features.file.Import("kernel32.IsWow64Process"), True),
        ("mimikatz", "file", capa.features.file.Import("msvcrt.exit"), True),
        ("mimikatz", "file", capa.features.file.Import("cabinet.#11"), True),
        ("mimikatz", "file", capa.features.file.Import("#11"), False),
        ("mimikatz", "file", capa.features.file.Import("#nope"), False),
        ("mimikatz", "file", capa.features.file.Import("nope"), False),
        # function/characteristic(loop)
        ("mimikatz", "function=0x401517", capa.features.Characteristic("loop"), True),
        ("mimikatz", "function=0x401000", capa.features.Characteristic("loop"), False),
        # function/characteristic(switch)
        pytest.param(
            "mimikatz",
            "function=0x409411",
            capa.features.Characteristic("switch"),
            True,
            marks=pytest.mark.xfail(reason="characteristic(switch) not implemented yet"),
        ),
        ("mimikatz", "function=0x401000", capa.features.Characteristic("switch"), False),
        # function/characteristic(calls to)
        pytest.param(
            "mimikatz",
            "function=0x401000",
            capa.features.Characteristic("calls to"),
            True,
            marks=pytest.mark.xfail(reason="characteristic(calls to) not implemented yet"),
        ),
        # function/characteristic(tight loop)
        ("mimikatz", "function=0x402EC4", capa.features.Characteristic("tight loop"), True),
        ("mimikatz", "function=0x401000", capa.features.Characteristic("tight loop"), False),
        # function/characteristic(stack string)
        ("mimikatz", "function=0x4556E5", capa.features.Characteristic("stack string"), True),
        ("mimikatz", "function=0x401000", capa.features.Characteristic("stack string"), False),
        # bb/characteristic(tight loop)
        ("mimikatz", "function=0x402EC4,bb=0x402F8E", capa.features.Characteristic("tight loop"), True),
        ("mimikatz", "function=0x401000,bb=0x401000", capa.features.Characteristic("tight loop"), False),
    ],
    indirect=["sample", "scope"],
)
def test_lancelot_features(sample, scope, feature, expected):
    extractor = get_lancelot_extractor(sample)
    features = scope(extractor)
    assert (feature in features) == expected


"""
def test_api_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x403BAC))
    assert capa.features.insn.API("advapi32.CryptAcquireContextW") in features
    assert capa.features.insn.API("advapi32.CryptAcquireContext") in features
    assert capa.features.insn.API("advapi32.CryptGenKey") in features
    assert capa.features.insn.API("advapi32.CryptImportKey") in features
    assert capa.features.insn.API("advapi32.CryptDestroyKey") in features
    assert capa.features.insn.API("CryptAcquireContextW") in features
    assert capa.features.insn.API("CryptAcquireContext") in features
    assert capa.features.insn.API("CryptGenKey") in features
    assert capa.features.insn.API("CryptImportKey") in features
    assert capa.features.insn.API("CryptDestroyKey") in features


def test_api_features_64_bit(sample_a198216798ca38f280dc413f8c57f2c2):
    features = extract_function_features(lancelot_utils.Function(sample_a198216798ca38f280dc413f8c57f2c2.ws, 0x4011B0))
    assert capa.features.insn.API("kernel32.GetStringTypeA") in features
    assert capa.features.insn.API("kernel32.GetStringTypeW") not in features
    assert capa.features.insn.API("kernel32.GetStringType") in features
    assert capa.features.insn.API("GetStringTypeA") in features
    assert capa.features.insn.API("GetStringType") in features
    # call via thunk in IDA Pro
    features = extract_function_features(lancelot_utils.Function(sample_a198216798ca38f280dc413f8c57f2c2.ws, 0x401CB0))
    assert capa.features.insn.API("msvcrt.vfprintf") in features
    assert capa.features.insn.API("vfprintf") in features


def test_string_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x40105D))
    assert capa.features.String("SCardControl") in features
    assert capa.features.String("SCardTransmit") in features
    assert capa.features.String("ACR  > ") in features
    # other strings not in this function
    assert capa.features.String("bcrypt.dll") not in features


def test_string_pointer_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x44EDEF))
    assert capa.features.String("INPUTEVENT") in features


def test_byte_features(sample_9324d1a8ae37a36ae560c37448c9705a):
    features = extract_function_features(lancelot_utils.Function(sample_9324d1a8ae37a36ae560c37448c9705a.ws, 0x406F60))
    wanted = capa.features.Bytes(b"\xED\x24\x9E\xF4\x52\xA9\x07\x47\x55\x8E\xE1\xAB\x30\x8E\x23\x61")
    # use `==` rather than `is` because the result is not `True` but a truthy value.
    assert wanted.evaluate(features) == True


def test_byte_features64(sample_lab21_01):
    features = extract_function_features(lancelot_utils.Function(sample_lab21_01.ws, 0x1400010C0))
    wanted = capa.features.Bytes(b"\x32\xA2\xDF\x2D\x99\x2B\x00\x00")
    # use `==` rather than `is` because the result is not `True` but a truthy value.
    assert wanted.evaluate(features) == True


def test_bytes_pointer_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x44EDEF))
    assert capa.features.Bytes("INPUTEVENT".encode("utf-16le")).evaluate(features) == True


def test_number_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x40105D))
    assert capa.features.insn.Number(0xFF) in features
    assert capa.features.insn.Number(0x3136B0) in features
    # the following are stack adjustments
    assert capa.features.insn.Number(0xC) not in features
    assert capa.features.insn.Number(0x10) not in features


def test_number_arch_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x40105D))
    assert capa.features.insn.Number(0xFF) in features
    assert capa.features.insn.Number(0xFF, arch=ARCH_X32) in features
    assert capa.features.insn.Number(0xFF, arch=ARCH_X64) not in features


def test_offset_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x40105D))
    assert capa.features.insn.Offset(0x0) in features
    assert capa.features.insn.Offset(0x4) in features
    assert capa.features.insn.Offset(0xC) in features
    # the following are stack references
    assert capa.features.insn.Offset(0x8) not in features
    assert capa.features.insn.Offset(0x10) not in features

    # this function has the following negative offsets
    # movzx   ecx, byte ptr [eax-1]
    # movzx   eax, byte ptr [eax-2]
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x4011FB))
    assert capa.features.insn.Offset(-0x1) in features
    assert capa.features.insn.Offset(-0x2) in features


def test_offset_arch_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x40105D))
    assert capa.features.insn.Offset(0x0) in features
    assert capa.features.insn.Offset(0x0, arch=ARCH_X32) in features
    assert capa.features.insn.Offset(0x0, arch=ARCH_X64) not in features


def test_nzxor_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x410DFC))
    assert capa.features.Characteristic("nzxor") in features  # 0x0410F0B


def get_bb_insn(f, va):
    # fetch the BasicBlock and Instruction instances for the given VA in the given function.
    for bb in f.basic_blocks:
        for insn in bb.instructions:
            if insn.va == va:
                return (bb, insn)
    raise KeyError(va)


def test_is_security_cookie(mimikatz):
    # not a security cookie check
    f = lancelot_utils.Function(mimikatz.ws, 0x410DFC)
    for va in [0x0410F0B]:
        bb, insn = get_bb_insn(f, va)
        assert capa.features.extractors.lancelot.insn.is_security_cookie(f, bb, insn) == False

    # security cookie initial set and final check
    f = lancelot_utils.Function(mimikatz.ws, 0x46C54A)
    for va in [0x46C557, 0x46C63A]:
        bb, insn = get_bb_insn(f, va)
        assert capa.features.extractors.lancelot.insn.is_security_cookie(f, bb, insn) == True


def test_mnemonic_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x40105D))
    assert capa.features.insn.Mnemonic("push") in features
    assert capa.features.insn.Mnemonic("movzx") in features
    assert capa.features.insn.Mnemonic("xor") in features

    assert capa.features.insn.Mnemonic("in") not in features
    assert capa.features.insn.Mnemonic("out") not in features


def test_peb_access_features(sample_a933a1a402775cfa94b6bee0963f4b46):
    features = extract_function_features(lancelot_utils.Function(sample_a933a1a402775cfa94b6bee0963f4b46.ws, 0xABA6FEC))
    assert capa.features.Characteristic("peb access") in features


def test_tight_loop_features(mimikatz):
    f = lancelot_utils.Function(mimikatz.ws, 0x402EC4)
    for bb in f.basic_blocks:
        if bb.va != 0x402F8E:
            continue
        features = extract_basic_block_features(f, bb)
        assert capa.features.Characteristic("tight loop") in features
        assert capa.features.basicblock.BasicBlock() in features


def test_tight_loop_bb_features(mimikatz):
    f = lancelot_utils.Function(mimikatz.ws, 0x402EC4)
    for bb in f.basic_blocks:
        if bb.va != 0x402F8E:
            continue
        features = extract_basic_block_features(f, bb)
        assert capa.features.Characteristic("tight loop") in features
        assert capa.features.basicblock.BasicBlock() in features


def test_cross_section_flow_features(sample_a198216798ca38f280dc413f8c57f2c2):
    features = extract_function_features(lancelot_utils.Function(sample_a198216798ca38f280dc413f8c57f2c2.ws, 0x4014D0))
    assert capa.features.Characteristic("cross section flow") in features

    # this function has calls to some imports,
    # which should not trigger cross-section flow characteristic
    features = extract_function_features(lancelot_utils.Function(sample_a198216798ca38f280dc413f8c57f2c2.ws, 0x401563))
    assert capa.features.Characteristic("cross section flow") not in features


def test_segment_access_features(sample_a933a1a402775cfa94b6bee0963f4b46):
    features = extract_function_features(lancelot_utils.Function(sample_a933a1a402775cfa94b6bee0963f4b46.ws, 0xABA6FEC))
    assert capa.features.Characteristic("fs access") in features


def test_thunk_features(sample_9324d1a8ae37a36ae560c37448c9705a):
    features = extract_function_features(lancelot_utils.Function(sample_9324d1a8ae37a36ae560c37448c9705a.ws, 0x407970))
    assert capa.features.insn.API("kernel32.CreateToolhelp32Snapshot") in features
    assert capa.features.insn.API("CreateToolhelp32Snapshot") in features




def test_switch_features(mimikatz):
    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x409411))
    assert capa.features.Characteristic("switch") in features

    features = extract_function_features(lancelot_utils.Function(mimikatz.ws, 0x409393))
    assert capa.features.Characteristic("switch") not in features


def test_recursive_call_feature(sample_39c05b15e9834ac93f206bc114d0a00c357c888db567ba8f5345da0529cbed41):
    features = extract_function_features(
        lancelot_utils.Function(sample_39c05b15e9834ac93f206bc114d0a00c357c888db567ba8f5345da0529cbed41.ws, 0x10003100)
    )
    assert capa.features.Characteristic("recursive call") in features

    features = extract_function_features(
        lancelot_utils.Function(sample_39c05b15e9834ac93f206bc114d0a00c357c888db567ba8f5345da0529cbed41.ws, 0x10007B00)
    )
    assert capa.features.Characteristic("recursive call") not in features


def test_loop_feature(sample_39c05b15e9834ac93f206bc114d0a00c357c888db567ba8f5345da0529cbed41):
    features = extract_function_features(
        lancelot_utils.Function(sample_39c05b15e9834ac93f206bc114d0a00c357c888db567ba8f5345da0529cbed41.ws, 0x10003D30)
    )
    assert capa.features.Characteristic("loop") in features

    features = extract_function_features(
        lancelot_utils.Function(sample_39c05b15e9834ac93f206bc114d0a00c357c888db567ba8f5345da0529cbed41.ws, 0x10007250)
    )
    assert capa.features.Characteristic("loop") not in features


def test_file_string_features(sample_bfb9b5391a13d0afd787e87ab90f14f5):
    features = extract_file_features(
        sample_bfb9b5391a13d0afd787e87ab90f14f5.ws, sample_bfb9b5391a13d0afd787e87ab90f14f5.path,
    )
    assert capa.features.String("WarStop") in features  # ASCII, offset 0x40EC
    assert capa.features.String("cimage/png") in features  # UTF-16 LE, offset 0x350E


def test_function_calls_to(sample_9324d1a8ae37a36ae560c37448c9705a):
    features = extract_function_features(lancelot_utils.Function(sample_9324d1a8ae37a36ae560c37448c9705a.ws, 0x406F60))
    assert capa.features.Characteristic("calls to") in features
    assert len(features[capa.features.Characteristic("calls to")]) == 1


def test_function_calls_to64(sample_lab21_01):
    features = extract_function_features(lancelot_utils.Function(sample_lab21_01.ws, 0x1400052D0))  # memcpy
    assert capa.features.Characteristic("calls to") in features
    assert len(features[capa.features.Characteristic("calls to")]) == 8


def test_function_calls_from(sample_9324d1a8ae37a36ae560c37448c9705a):
    features = extract_function_features(lancelot_utils.Function(sample_9324d1a8ae37a36ae560c37448c9705a.ws, 0x406F60))
    assert capa.features.Characteristic("calls from") in features
    assert len(features[capa.features.Characteristic("calls from")]) == 23


def test_basic_block_count(sample_9324d1a8ae37a36ae560c37448c9705a):
    features = extract_function_features(lancelot_utils.Function(sample_9324d1a8ae37a36ae560c37448c9705a.ws, 0x406F60))
    assert len(features[capa.features.basicblock.BasicBlock()]) == 26


def test_indirect_call_features(sample_a933a1a402775cfa94b6bee0963f4b46):
    features = extract_function_features(lancelot_utils.Function(sample_a933a1a402775cfa94b6bee0963f4b46.ws, 0xABA68A0))
    assert capa.features.Characteristic("indirect call") in features
    assert len(features[capa.features.Characteristic("indirect call")]) == 3


def test_indirect_calls_resolved(sample_c91887d861d9bd4a5872249b641bc9f9):
    features = extract_function_features(lancelot_utils.Function(sample_c91887d861d9bd4a5872249b641bc9f9.ws, 0x401A77))
    assert capa.features.insn.API("kernel32.CreatePipe") in features
    assert capa.features.insn.API("kernel32.SetHandleInformation") in features
    assert capa.features.insn.API("kernel32.CloseHandle") in features
    assert capa.features.insn.API("kernel32.WriteFile") in features
"""