# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import warnings

from typing import Callable, Dict, Optional

from torch.utils.data import IterDataPipe, MapDataPipe
from torch.utils.data.datapipes.utils.common import check_lambda_fn, DILL_AVAILABLE

if DILL_AVAILABLE:
    import dill

    dill.extend(use_dill=False)


# @functional_datapipe("to_map_datapipe")  # This line must be kept for .pyi signature parser
class IterToMapConverterMapDataPipe(MapDataPipe):
    r"""
    Lazily load data from ``IterDataPipe`` to construct a ``MapDataPipe`` with
    the key-value pair generated by ``key_value_fn`` (functional name: ``to_map_datapipe``).
    If ``key_value_fn`` is not given, each data from the source IterDataPipe must itself be an iterable
    with exactly two objects. The first object of each item becomes a key in
    the new dictionary, and the second object the corresponding value.

    Args:
        datapipe: Source IterDataPipe
        key_value_fn: Function being applied over each data to generate key-value pair

    Note:
        If a key being added is already present, the corresponding value
        will be replaced by the new value.
    """
    datapipe: IterDataPipe
    key_value_fn: Optional[Callable]
    _map: Optional[Dict]
    _length: int

    def __init__(self, datapipe: IterDataPipe, key_value_fn: Optional[Callable] = None):
        if not isinstance(datapipe, IterDataPipe):
            raise TypeError(f"IterToMapConverter can only apply on IterDataPipe, but found {type(datapipe)}")
        self.datapipe = datapipe
        check_lambda_fn(key_value_fn)
        self.key_value_fn = key_value_fn  # type: ignore[assignment]
        self._map = None
        self._length = -1

    def _load_map(self):
        self._map = {}
        for d in self.datapipe:
            inp = d if self.key_value_fn is None else self.key_value_fn(d)
            try:
                length = len(inp)
            except TypeError:
                raise TypeError(f"Cannot convert dictionary update element {type(inp)} ({inp}) to a sequence")
            if length != 2:
                raise ValueError(f"dictionary update sequence element has length {length}, 2 is required")
            key, value = inp
            if key in self._map:
                warnings.warn(f"Found duplicate key {key}. Please check your `key_value_fn`")
            self._map[key] = value

    def __getitem__(self, index):
        if self._map is None:
            self._load_map()
        return self._map[index]  # type: ignore[index]

    def __len__(self):
        if self._length > -1:
            return self._length
        if self._map is not None:
            self._length = len(self._map)  # type: ignore[arg-type]
            return self._length
        try:
            self._length = len(self.datapipe)
            return self._length
        except (TypeError, NotImplementedError):
            self._length = -1
        if self._map is None:
            warnings.warn(
                "Data from prior DataPipe are loaded to get length of"
                "IterToMapConverter before execution of the pipeline."
                "Please consider removing len()."
            )
            self._load_map()
            self._length = len(self._map)  # type: ignore[arg-type]
        return self._length

    def __getstate__(self):
        if self._map is None:
            self._load_map()
        if DILL_AVAILABLE:
            dill_key_value_fn = dill.dumps(self.key_value_fn)
        else:
            dill_key_value_fn = self.key_value_fn
        return (
            self.datapipe,
            dill_key_value_fn,
            self._map,
            self._length,
        )

    def __setstate__(self, state):
        (self.datapipe, dill_key_value_fn, self._map, self._length) = state
        if DILL_AVAILABLE:
            self.key_value_fn = dill.loads(dill_key_value_fn)  # type: ignore[assignment]
        else:
            self.key_value_fn = dill_key_value_fn  # type: ignore[assignment]


# Register for functional API
# See https://github.com/pytorch/data/issues/200
IterDataPipe.register_datapipe_as_function("to_map_datapipe", IterToMapConverterMapDataPipe)
