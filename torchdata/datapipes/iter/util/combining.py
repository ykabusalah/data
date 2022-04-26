# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import warnings
from collections import OrderedDict
from typing import Callable, Iterator, Optional, TypeVar

from torch.utils.data import functional_datapipe, IterDataPipe, MapDataPipe
from torch.utils.data.datapipes.utils.common import _check_lambda_fn

T_co = TypeVar("T_co", covariant=True)


@functional_datapipe("zip_with_iter")
class IterKeyZipperIterDataPipe(IterDataPipe[T_co]):
    r"""
    Zips two IterDataPipes together based on the matching key (functional name: ``zip_with_iter``). The keys
    are computed by ``key_fn`` and ``ref_key_fn`` for the two IterDataPipes, respectively. When there isn't a match
    between the elements of the two IterDataPipes, the element from ``ref_datapipe`` is stored in a buffer. Then, the
    next element from ``ref_datapipe`` is tried. After a match is found, the ``merge_fn`` determines how they will
    be combined and returned (a tuple is generated by default).

    Args:
        source_datapipe: IterKeyZipper will yield data based on the order of this IterDataPipe
        ref_datapipe: Reference IterDataPipe from which IterKeyZipper will find items
            with matching key for ``source_datapipe``
        key_fn: Callable function that will compute keys using elements from ``source_datapipe``
        ref_key_fn: Callable function that will compute keys using elements from ``ref_datapipe``
            If it's not specified, the ``key_fn`` will also be applied to elements from ``ref_datapipe``
        keep_key: Option to yield the matching key along with the items in a tuple,
            resulting in `(key, merge_fn(item1, item2))`.
        buffer_size: The size of buffer used to hold key-data pairs from reference DataPipe until a match is found.
            If it's specified as ``None``, the buffer size is set as infinite.
        merge_fn: Function that combines the item from ``source_datapipe`` and the item from ``ref_datapipe``,
            by default a tuple is created

    Example:
        >>> from torchdata.datapipes.iter import IterableWrapper
        >>> from operator import itemgetter
        >>> def merge_fn(t1, t2):
        >>>     return t1[1] + t2[1]
        >>> dp1 = IterableWrapper([('a', 100), ('b', 200), ('c', 300)])
        >>> dp2 = IterableWrapper([('a', 1), ('b', 2), ('c', 3), ('d', 4)])
        >>> res_dp = dp1.zip_with_iter(dp2, key_fn=itemgetter(0),
        >>>                            ref_key_fn=itemgetter(0), keep_key=True, merge_fn=merge_fn)
        >>> list(res_dp)
        [('a', 101), ('b', 202), ('c', 303)]
    """

    def __init__(
        self,
        source_datapipe: IterDataPipe,
        ref_datapipe: IterDataPipe,
        key_fn: Callable,
        ref_key_fn: Optional[Callable] = None,
        keep_key: bool = False,
        buffer_size: int = 10000,
        merge_fn: Optional[Callable] = None,
    ) -> None:
        if not isinstance(ref_datapipe, IterDataPipe):
            raise TypeError(f"ref_datapipe must be a IterDataPipe, but its type is {type(ref_datapipe)} instead.")
        self.source_datapipe = source_datapipe
        self.ref_datapipe = ref_datapipe
        _check_lambda_fn(key_fn)
        self.key_fn = key_fn
        if ref_key_fn is not None:
            _check_lambda_fn(ref_key_fn)
        self.ref_key_fn = key_fn if ref_key_fn is None else ref_key_fn
        self.keep_key = keep_key
        if merge_fn is not None:
            _check_lambda_fn(merge_fn)
        self.merge_fn = merge_fn
        if buffer_size is not None and buffer_size <= 0:
            raise ValueError("'buffer_size' is required to be either None or a positive integer.")
        self.buffer_size: int = buffer_size

    def __iter__(self) -> Iterator:
        buffer: OrderedDict = OrderedDict()
        ref_it = iter(self.ref_datapipe)
        warn_once_flag = True
        for data in self.source_datapipe:
            key = self.key_fn(data)
            while key not in buffer:
                try:
                    ref_data = next(ref_it)
                except StopIteration:
                    raise BufferError(
                        f"No matching key can be found from reference DataPipe for the data {data}. "
                        "Please consider increasing the buffer size."
                    )
                ref_key = self.ref_key_fn(ref_data)
                if ref_key in buffer:
                    raise ValueError("Duplicate key is found in reference DataPipe")
                if self.buffer_size is not None and len(buffer) > self.buffer_size:
                    if warn_once_flag:
                        warn_once_flag = False
                        warnings.warn(
                            "Buffer reaches the upper limit, so reference key-data pair begins to "
                            "be removed from buffer in FIFO order. Please consider increase buffer size."
                        )
                    buffer.popitem(last=False)
                buffer[ref_key] = ref_data
            res = self.merge_fn(data, buffer.pop(key)) if self.merge_fn else (data, buffer.pop(key))
            if self.keep_key:
                yield key, res
            else:
                yield res

    def __len__(self) -> int:
        return len(self.source_datapipe)


@functional_datapipe("zip_with_map")
class MapKeyZipperIterDataPipe(IterDataPipe[T_co]):
    r"""
    Joins the items from the source IterDataPipe with items from a MapDataPipe (functional name: ``zip_with_map``).
    The matching is done by the provided ``key_fn``, which maps an item from ``source_iterdatapipe`` to
    a key that should exist in the ``map_datapipe``. The return value is created by the ``merge_fn``, which returns
    a tuple of the two items by default.

    Args:
        source_iterdatapipe: IterDataPipe from which items are yield and will be combined with an item
            from ``map_datapipe``
        map_datapipe: MapDataPipe that takes a key from ``key_fn``, and returns an item
        key_fn: Function that maps each item from ``source_iterdatapipe`` to a key that exists in ``map_datapipe``
        merge_fn: Function that combines the item from ``source_iterdatapipe`` and the matching item
            from ``map_datapipe``, by default a tuple is created

    Example:
        >>> from torchdata.datapipes.iter import IterableWrapper
        >>> from torchdata.datapipes.map import SequenceWrapper
        >>> from operator import itemgetter
        >>> def merge_fn(tuple_from_iter, value_from_map):
        >>>     return tuple_from_iter[0], tuple_from_iter[1] + value_from_map
        >>> dp1 = IterableWrapper([('a', 1), ('b', 2), ('c', 3)])
        >>> mapdp = SequenceWrapper({'a': 100, 'b': 200, 'c': 300, 'd': 400})
        >>> res_dp = dp1.zip_with_map(map_datapipe=mapdp, key_fn=itemgetter(0), merge_fn=merge_fn)
        >>> list(res_dp)
        [('a', 101), ('b', 202), ('c', 303)]
    """

    def __init__(
        self,
        source_iterdatapipe: IterDataPipe,
        map_datapipe: MapDataPipe,
        key_fn: Callable,
        merge_fn: Optional[Callable] = None,
    ):
        if not isinstance(map_datapipe, MapDataPipe):
            raise TypeError(f"map_datapipe must be a MapDataPipe, but its type is {type(map_datapipe)} instead.")
        self.source_iterdatapipe: IterDataPipe = source_iterdatapipe
        self.map_datapipe: MapDataPipe = map_datapipe
        _check_lambda_fn(key_fn)
        self.key_fn: Callable = key_fn
        if merge_fn is not None:
            _check_lambda_fn(merge_fn)
        self.merge_fn: Optional[Callable] = merge_fn
        self.length: int = -1

    def __iter__(self) -> Iterator:
        for item in self.source_iterdatapipe:
            key = self.key_fn(item)
            try:
                map_item = self.map_datapipe[key]
            except (KeyError, IndexError):
                raise KeyError(f"key_fn maps {item} to {key}, which is not a valid key in the given MapDataPipe.")
            yield self.merge_fn(item, map_item) if self.merge_fn else (item, map_item)

    def __len__(self) -> int:
        if self.length == -1:
            self.length = len(self.source_iterdatapipe)
        return self.length
