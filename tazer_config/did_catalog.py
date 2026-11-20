#!/usr/bin/env python3
"""
did_catalog.py - loads did_map.json (the body-config DID / bit-field map extracted
from the decrypted Tazer firmware). Labels are filled in by the diffing workflow.
"""
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_HERE, 'did_map.json')

class Field:
    def __init__(self, d):
        self.byte = d.get('byte'); self.mask = d.get('mask')
        self.origin = d.get('origin', ''); self.label = d.get('label')
        self.confirmed = bool(d.get('confirmed'))
    def desc(self):
        b = f'byte {self.byte}' if self.byte is not None else 'byte ?'
        m = ('mask 0x%02X' % self.mask) if self.mask else 'mask ?'
        return f'{b} · {m} · {self.origin}'

class Block:
    def __init__(self, label, source, confirmed, fields):
        self.label = label; self.source = source
        self.confirmed = confirmed; self.fields = fields

class Catalog:
    def __init__(self, path=_PATH):
        self.path = path
        raw = json.load(open(path))
        self.bcm_request_id = int(raw.get('bcm_request_id', '0x620'), 16)
        self.blocks = {}
        for k, v in raw['dids'].items():
            did = int(k, 16)
            if isinstance(v, list):                      # legacy format: bare field list
                self.blocks[did] = Block(None, None, False, [Field(f) for f in v])
            else:                                        # {block_label, fields:[...]}
                self.blocks[did] = Block(v.get('block_label'), v.get('block_source'),
                                         bool(v.get('block_confirmed')),
                                         [Field(f) for f in v.get('fields', [])])
    @property
    def all_dids(self):
        return sorted(self.blocks.keys())
    def fields(self, did):
        b = self.blocks.get(did)
        return b.fields if b else []
    def block_label(self, did):
        b = self.blocks.get(did)
        return b.label if b else None

def load(path=_PATH):
    return Catalog(path)
