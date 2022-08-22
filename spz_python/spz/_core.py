import numpy as np
import pandas as pd

from .sparsetype import DC, C, S, abbreviate, unabbreviate


def repeatrange(repeat, *args):
    """e.g., [0, 1, 2, 0, 1, 2]"""
    return np.repeat(np.arange(*args)[None, :], repeat, axis=0).ravel()


def issorted(array):
    return np.all(array[:-1] <= array[1:])


class SPZ:
    def __init__(self, arrays, shape=None, structure=None):
        if not isinstance(arrays, (list, tuple)):
            raise TypeError("arrays argument must be a list or tuple of numpy arrays")
        if not arrays:
            raise ValueError("At least one array must be given")
        arrays = [np.array(array) for array in arrays]
        if not all(array.ndim == 1 for array in arrays):
            raise ValueError("arrays must be a single dimension")
        size = arrays[0].size
        if not all(array.size == size for array in arrays):
            raise ValueError("arrays must be the same size")
        if not all(np.issubdtype(array.dtype, np.integer) for array in arrays):
            raise ValueError("arrays must be integer dtype")
        if not all((array >= 0).all() for array in arrays):
            raise ValueError("array values must be positive")

        if shape is not None:
            self._shape = tuple(shape)
            if not all(dimsize > 0 for dimsize in self._shape):
                raise ValueError("Dimension sizes must be greater than 0")
            if len(self._shape) != len(arrays):
                raise ValueError("shape must be the same length as arrays")
            if not all((array < dimsize).all() for array, dimsize in zip(arrays, self._shape)):
                raise ValueError("index in array is out of bounds")
        else:
            self._shape = tuple(int(array.max()) + 1 for array in arrays)

        if structure is None:  # Assume CSF
            self._structure = [DC] * (len(arrays) - 1) + [S]
        elif isinstance(structure, str):
            self._structure = unabbreviate(structure)
        else:
            self._structure = unabbreviate(abbreviate(*structure))
        if len(self._structure) != len(arrays):
            raise ValueError("structure must be the same length as arrays")
        if self._structure[-1] != S:
            # C as the final dimension means "dense"
            raise ValueError("The final dimension must be sparse structural type")

        # Now the fun part!  Generate the compressed structure from COO
        df = pd.DataFrame(arrays).T.sort_values(list(range(self.ndim)))
        if df.duplicated().any():
            raise ValueError("Duplicate indices found!")

        # First create indices
        indices = []
        cols = list(df.columns)
        num_s_levels = 0
        prev = None
        for sparsity, level in zip(self._structure, range(df.shape[-1])):
            if sparsity == S:
                num_s_levels += 1
            elif sparsity == DC:
                subdf = df[cols[: level + 1]].drop_duplicates()
                for i in range(-num_s_levels - 1, 0):
                    indices.append(subdf.iloc[:, i].values)
                num_s_levels = 0
            elif sparsity == C:
                if level == 0:
                    indices.append(np.arange(shape[level]))
                elif prev == DC:
                    subdf = df[cols[:level]].drop_duplicates()
                    indices.append(repeatrange(len(subdf), shape[level]))
                elif prev == S:
                    subdf = df[cols[:level]].drop_duplicates()
                    subdf = subdf.join(
                        pd.DataFrame({cols[level]: range(shape[level])}), how="cross"
                    )
                    for i in range(-num_s_levels - 1, 0):
                        indices.append(subdf.iloc[:, i].values)
                    num_s_levels = 0
                else:  # prev == C
                    indices.append(repeatrange(indices[-1].size, shape[level]))
            prev = sparsity
        for i in range(-num_s_levels, 0):
            indices.append(df.iloc[:, i].values)
        self._indices = indices

        # Now create pointers
        pointers = []
        for sparsity, level in zip(self._structure[:-1], range(df.shape[-1] - 1)):
            if sparsity == S:
                ptr = np.arange(indices[level].size + 1)
            elif self._structure[level + 1] == C:
                ptr = np.arange(len(indices[level]) + 1) * shape[level + 1]
                if sparsity == C:
                    # Update subdf to use later
                    if level == 0:
                        subdf = pd.DataFrame({cols[level]: range(shape[level])})
                    elif self._structure[level - 1] == C:
                        subdf = subdf.join(
                            pd.DataFrame({cols[level]: range(shape[level])}), how="cross"
                        )
                    else:
                        subdf = df[cols[:level]].drop_duplicates()
                        subdf = subdf.join(
                            pd.DataFrame({cols[level]: range(shape[level])}), how="cross"
                        )
            elif sparsity == DC:
                if self._structure[level + 1] == DC:
                    subdf = df[cols[: level + 2]].drop_duplicates()
                else:  # sparsity[level + 1] == S
                    # number of "S" immediately after this level
                    nums = 0
                    for item in self._structure[level + 1 :]:
                        if item == S:
                            nums += 1
                        else:
                            break
                    subdf = df[cols[: level + nums + 1]].drop_duplicates()
                    if len(self._structure) > level + nums + 1:
                        if self._structure[level + nums + 1] == C:
                            subdf = subdf.join(
                                pd.DataFrame(
                                    {cols[level + nums + 1]: range(shape[level + nums + 1])}
                                ),
                                how="cross",
                            )
                        elif self._structure[level + nums + 1] == DC:
                            subdf = df[cols[: level + nums + 2]].drop_duplicates()
                ptr = np.zeros(indices[level].size + 1, int)
                ptr[1:] = subdf.groupby(cols[: level + 1])[cols[level + 1]].count().cumsum()
            elif sparsity == C:
                if level > 0:
                    if self._structure[level - 1] == C:
                        subdf1 = subdf
                    else:
                        subdf1 = df[cols[:level]].drop_duplicates()
                subdf = pd.DataFrame({cols[level]: range(shape[level])})
                if level > 0:
                    subdf = subdf1.join(subdf, how="cross")
                if self._structure[level + 1] == DC:
                    subdf2 = df[cols[: level + 2]].drop_duplicates()
                else:  # sparsity[level + 1] == S
                    # number of "S" immediately after this level
                    nums = 0
                    for item in self._structure[level + 1 :]:
                        if item == S:
                            nums += 1
                        else:
                            break
                    subdf2 = df[cols[: level + nums + 1]].drop_duplicates()
                    if len(self._structure) > level + nums + 1:
                        if self._structure[level + nums + 1] == C:
                            subdf2 = subdf2.join(
                                pd.DataFrame(
                                    {cols[level + nums + 1]: range(shape[level + nums + 1])}
                                ),
                                how="cross",
                            )
                        elif self._structure[level + nums + 1] == DC:
                            subdf2 = df[cols[: level + nums + 2]].drop_duplicates()
                subdf3 = subdf.merge(subdf2, how="left")
                subdf3[level + 1] = subdf3[level + 1].notnull()
                ptr = np.zeros(indices[level].size + 1, int)
                ptr[1:] = subdf3.groupby(cols[: level + 1])[level + 1].sum().cumsum()
            pointers.append(ptr)
        self._pointers = pointers
        # TODO: can we detect and change sparsity type to be more efficient?
        # For example, so we don't need to store a pointers or indices.

    def _validate(self):
        indices = self._indices
        pointers = self._pointers
        structure = self._structure
        ndim = self.ndim
        assert len(indices) == len(pointers) + 1 == ndim
        for idx in indices:
            assert idx.dtype == int
        for ptr in pointers:
            assert ptr.dtype == int
        for idx, ptr in zip(indices[:-1], pointers):
            assert len(ptr) == len(idx) + 1
        for idx, ptr in zip(indices[1:], pointers):
            assert ptr[0] == 0
            assert ptr[-1] == len(idx)
        for ptr in pointers:
            assert issorted(ptr)
        assert issorted(indices[0])
        for idx, ptr in zip(indices[1:], pointers):
            for start, stop in zip(ptr[:-1], ptr[1:]):
                assert issorted(idx[start:stop])
        assert structure[-1] == S
        for i, (sparsity, idx, ptr) in enumerate(zip(structure[:-1], indices, pointers[:-1])):
            if sparsity == C:
                if i == 0:
                    assert len(idx) == self.shape[0]
                elif structure[i - 1] != S:
                    assert len(idx) == len(self._indices[i - 1]) * self.shape[i]
            elif sparsity == S:
                assert len(idx) == len(indices[i + 1])
            elif sparsity == DC:
                if i == 0:
                    assert len(idx) == len(set(idx))
                assert len(ptr) == len(set(ptr))
            else:  # pragma: no cover
                raise AssertionError()

    def as_structure(self, structure):
        return SPZ(self.arrays, self.shape, structure)

    def get_index(self, dim):
        return self._indices[dim]

    def get_pointers(self, dim):
        return self._pointers[dim]

    @property
    def indices(self):
        rv = list(self._indices)
        for i, sparsity in enumerate(self._structure):
            if sparsity == C:
                rv[i] = None
        return rv

    @property
    def pointers(self):
        rv = list(self._pointers)
        for i, sparsity in enumerate(self._structure[:-1]):
            if sparsity == S:
                rv[i] = None
            elif sparsity == C and i > 0:
                rv[i - 1] = None
        return rv

    @property
    def ndim(self):
        return len(self._shape)

    @property
    def shape(self):
        return self._shape

    @property
    def structure(self):
        return self._structure

    @property
    def abbreviation(self):
        return abbreviate(self._structure)

    @property
    def arrays(self):
        return [np.array(array) for array in zip(*_to_coo(self._indices, self._pointers))]


def _to_coo(indices, pointers, start=0, stop=None):
    index, *indices = indices
    if stop is None:
        stop = len(index)
    if not indices:
        for idx in index[start:stop]:
            yield (idx,)
        return
    ptrs, *pointers = pointers
    for idx, start, stop in zip(index[start:stop], ptrs[start:stop], ptrs[start + 1 : stop + 1]):
        for indexes in _to_coo(indices, pointers, start, stop):
            yield (idx,) + indexes
