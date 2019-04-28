# pylint: disable-msg=too-many-arguments
"""Definition of Grid functions in BEM++"""

import numba as _numba
import numpy as _np

from bempp.api.grid.grid import GridData as _GridData


def real_callable(*args, jit=True):
    """JIT Compile a callable for a grid function if jit is true."""

    def wrap(f):
        """Actual wrapper."""
        if jit:
            fun = _numba.njit(
                _numba.void(
                    _numba.float64[:],
                    _numba.float64[:],
                    _numba.uint32,
                    _numba.float64[:],
                )
            )(f)
        else:
            fun = f
        fun.bempp_type = "real"
        return fun

    if not args:
        return wrap
    else:
        return wrap(args[0])


def complex_callable(*args, jit=True):
    """JIT Compile a callable for a grid function if jit is true."""

    def wrap(f):
        """Actual wrapper."""
        if jit:
            fun = _numba.njit(
                _numba.void(
                    _numba.float64[:],
                    _numba.float64[:],
                    _numba.uint32,
                    _numba.complex128[:],
                )
            )(f)
        else:
            fun = f
        fun.bempp_type = "complex"
        return fun

    if not args:
        return wrap
    else:
        return wrap(args[0])


class GridFunction(object):
    """
    Representation of functions on a grid.

    Attributes
    ----------
    coefficients : np.ndarray
        Return or set the vector of coefficients.
    component_count : int
        Return the number of components of the grid
        function values.
    space : bemp.api.space.Space
        Return the space over which the GridFunction is defined.
    grid : bempp.api.grid.Grid
        Return the underlying grid.
    parameters : bempp.api.ParameterList
        Return the set of parameters.
    representation : string
        Return 'primal' if the coefficients of the Gridfunction
        are known. Return 'dual' if only the coefficients in the
        dual space are known.

    """

    def __init__(
        self,
        space,
        dual_space=None,
        fun=None,
        coefficients=None,
        projections=None,
        parameters=None,
    ):
        """
        Construct a grid function.

        A grid function can be initialized in three different ways.

        1. By providing a Python callable. Any Python callable of the
           following form is valid.::

                callable(x,n,domain_index,result)

           Here, x, n, and result are all numpy arrays. x contains the current
           evaluation point, n the associated outward normal direction and
           result is a numpy array that will store the result of the Python
           callable. The variable domain_index stores the index of the
           subdomain on which x lies (default 0). This makes it possible to
           define different functions for different subdomains.

           The following example defines input data that is the inner product
           of the coordinate x with the normal direction n.::

                fun(x,n,domain_index,result):
                    result[0] =  np.dot(x,n)

        2. By providing a vector of coefficients at the nodes. This is
           preferable if the coefficients of the data are coming from an
           external code.

        3. By providing a vector of projection data and a corresponding
           dual space.

        Parameters
        ----------
        space : bempp.api.space.Space
            The space over which the GridFunction is defined.
        dual_space : bempp.api.Space
            A representation of the dual space. If not specified
            then space == dual_space is assumed (optional).
        fun : callable
            A Python function from which the GridFunction is constructed
            (optional).
        coefficients : np.ndarray
            A 1-dimensional array with the coefficients of the GridFunction
            at the interpolatoin points of the space (optional).
        projections : np.ndarray
            A 1-dimensional array with the projections of the GridFunction
            onto a dual space (optional).
        parameters : bempp.api.ParameterList
            A ParameterList object used for the assembly of
            the GridFunction (optional).

        Notes
        -----
        * Only one of projections, coefficients, or fun is allowed as
          parameter.

        Examples
        --------
        To create a GridFunction from a Python callable my_fun use

        >>> grid_function = GridFunction(space, fun=my_fun)

        To create a GridFunction from a vector of coefficients coeffs use

        >>> grid_function = GridFunction(space,coefficients=coeffs)

        To create a GridFunction from a vector of projections proj use

        >>> grid_function = GridFunction(
                space,dual_space=dual_space, projections=proj)

        """
        from bempp.api.utils.helpers import assign_parameters

        self._space = None
        self._dual_space = None
        self._coefficients = None
        self._projections = None
        self._representation = None

        self._space = space

        if dual_space is None:
            dual_space = space

        self._dual_space = dual_space

        self._parameters = assign_parameters(parameters)

        if sum(1 for e in [fun, coefficients, projections] if e is not None) != 1:
            raise ValueError(
                "Exactly one of 'fun', 'coefficients' or 'projections' "
                + "must be nonzero."
            )

        if coefficients is not None:
            self._coefficients = coefficients
            self._representation = 'primal'

        if projections is not None:
            self._projections = projections
            self._representation = 'dual'

        if fun is not None:
            from bempp.api.integration.triangle_gauss import rule

            points, weights = rule(self._parameters.quadrature.regular)

            if fun.bempp_type == "real":
                dtype = "float64"
            else:
                dtype = "complex128"

            self._projections = _np.zeros(dual_space.global_dof_count, dtype=dtype)

            # Create a Numba callable from the function

            _project_function(
                fun,
                dual_space.grid.data,
                dual_space.support,
                dual_space.local2global,
                dual_space.local_multipliers,
                dual_space.numba_evaluate,
                dual_space.shapeset.evaluate,
                points,
                weights,
                space.codomain_dimension,
                self._projections,
            )

            self._representation = 'dual'

    @property
    def space(self):
        """Return space."""
        return self._space

    @property
    def dtype(self):
        """Return type."""
        if self._coefficients is not None:
            return self._coefficients.dtype
        if self._projections is not None:
            return self._projections.dtype

    @property
    def parameters(self):
        """Return parameters."""
        return self._parameters

    @property
    def dual_space(self):
        """Return dual space."""
        return self._dual_space

    @property
    def representation(self):
        """
        Return the representation of the grid function.

        If the grid function is given in terms of coefficients in the
        domain space return 'primal'. If the function is given by its
        projections return 'dual'.
        """
        return self._representation


    @property
    def coefficients(self):
        """Return coefficient vector."""
        if self._coefficients is None:
            from bempp.api.operators.boundary.sparse import identity
            from scipy.sparse.linalg import spsolve

            mat = (
                identity(
                    self.space, self.space, self.dual_space, parameters=self.parameters
                )
                .weak_form()
                .A
            )
            self._coefficients = spsolve(mat, self._projections)
            self._representation = 'primal'

        return self._coefficients

    @property
    def real(self):
        """Return a new grid function consisting of the real part of this function."""
        import numpy as np
        import bempp.api
        if self.representation == 'primal':
            return bempp.api.GridFunction(
                space=self.space, dual_space=self.dual_space,
                coefficients=np.real(self.coefficients))
        else:
            return bempp.api.GridFunction(
                space=self.space, dual_space=self.dual_space,
                projections=np.real(self.projections()))

    @property
    def imag(self):
        """Return a new grid function consisting of the imaginary part of this function."""
        import numpy as np
        import bempp.api
        if self.representation == 'primal':
            return bempp.api.GridFunction(
                space=self.space, dual_space=self.dual_space,
                coefficients=np.imag(self.coefficients))
        else:
            return bempp.api.GridFunction(
                space=self.space, dual_space=self.dual_space,
                projections=np.imag(self.projections()))


    @property
    def component_count(self):
        """Return number of components."""
        return self.space.codomain_dimension

    def projections(self, dual_space=None):
        """
        Compute the vector of projections onto the given dual space.

        Parameters
        ----------
        dual_space : bempp.api.space.Space
            A representation of the dual space. If not specified
            then fun.dual_space is used.

        Returns
        -------
        out : np.ndarray
            A vector of projections onto the dual space.

        """
        import bempp.api

        if (dual_space == self._dual_space and
                self._projections is not None):
            return self._projections

        ident = bempp.api.operators.boundary.sparse.identity(
            self.space, self.space, dual_space).weak_form()
        self._dual_space = dual_space
        self._projections = ident * self.coefficients

        return self._projections


    def plot(self, mode="element", transformation="real"):
        """
        Plot the grid function.
        
        Attributes
        ----------
        mode : string
            One of 'element' or 'node'. If 'element' is chosen
            the color is determined by the mid-point of the faces
            of the grid. For 'vertices' the vertex values are
            chosen (default: 'element')
        transformation : string or object
            One of 'real', 'imag', 'abs', 'log_abs' or
            'abs_squared' or a callable object. 
            Describes the data transformation
            before plotting. For functions with vector values
            only 'abs', 'log_abs' or 'abs_squared' are allowed.
            If a callable object is given this is applied instead.
            It is important that the callable returns numpy arrays
            with the same number of dimensions as before.
        
        """
        import bempp.api
        from bempp.api.external.viewers import visualize

        visualize(self, mode, transformation)

    def evaluate(self, element, local_coordinates):
        """Evaluate grid function on a single element."""
        coefficients = self.coefficients
        # Get global dof ids and weights
        global_dofs = self.space.local2global[element.index]
        element_values = self.space.evaluate(element, local_coordinates)
        return _np.tensordot(element_values, coefficients[global_dofs], axes=([1], [0]))

    def evaluate_on_element_centers(self):
        """Evaluate the grid function on all element centers."""
        grid = self.space.grid
        local_coordinates = _np.array([[1.0 / 3], [1.0 / 3]])

        values = _np.zeros(
            (self.component_count, grid.number_of_elements), dtype=self.dtype
        )
        for element in grid.entity_iterator(0):
            local_values = self.evaluate(element, local_coordinates)
            values[:, element.index] = local_values.flat
        return values

    def evaluate_on_vertices(self):
        """
        Evaluate the grid function on all vertices.
        
        If a function is discontinuous across elements a weighted average
        of the element values at the vertices is taken.
        
        """
        grid = self.space.grid
        local_coordinates = _np.array([[0, 1, 0], [0, 0, 1]], dtype="float64")

        values = _np.zeros(
            (self.component_count, grid.number_of_vertices), dtype=self.dtype
        )

        # Sum up the areas of all elements adjacent to the vertices
        vertex_areas = _np.zeros(grid.number_of_elements, dtype='float64')

        for element in grid.entity_iterator(0):
            local_values = self.evaluate(element, local_coordinates)
            for i in range(3):
                index = grid.elements[i, element.index]
                element_area = element.geometry.volume
                vertex_areas[index] += element_area
                values[:, index] += local_values[:, i] * element_area
        return values / vertex_areas


    def l2_norm(self):
        """L^2 norm of the function"""
        import bempp.api
        import numpy as np

        # L2-Norm on the whole space
        mass = self.space.mass_matrix()
        vec = self.coefficients
        return np.sqrt(np.abs(vec.conjugate().T.dot(mass.dot(vec))))

    def __add__(self, other):
        """Add two grid functions."""

        if self.space != other.space:
            raise ValueError("Spaces are not identical.")

        if self.representation == 'dual' and other.representation == 'dual':
            if self.dual_space == other.dual_space:
                return GridFunction(
                    self.space,
                    projections=self.projections() + other.projections(),
                    dual_space=self.dual_space)

        return GridFunction(self.space,
                            coefficients=self.coefficients + other.coefficients)

    def __mul__(self, alpha):
        import numpy as np

        if np.isscalar(alpha):
            if self.representation == 'dual':
                return GridFunction(self.space,
                                    projections=alpha * self._projections,
                                    dual_space=self.dual_space,
                                    parameters=self.parameters)
            else:
                return GridFunction(self.space,
                                    coefficients=alpha * self.coefficients,
                                    parameters=self.parameters)
        else:
            return NotImplemented

    def __rmul__(self, alpha):
        import numpy as np

        if np.isscalar(alpha):
            return self * alpha
        else:
            return NotImplemented

    def __div__(self, alpha):
        return self * (1. / alpha)

    def __truediv__(self, alpha):
        return self.__div__(alpha)

    def __neg__(self):
        return self.__mul__(-1.0)

    def __sub__(self, other):
        if self.space != other.space:
            raise ValueError("Spaces are not identical.")

        return self + (-other)

    @classmethod
    def from_random(cls, space):
        """Create a random grid function normalized to unit norm. """
        from numpy.random import randn
        ndofs = space.global_dof_count
        fun = cls(space, coefficients=randn(ndofs))
        return fun / fun.l2_norm()

    @classmethod
    def from_ones(cls, space):
        """Create a grid function with all coefficients set to one. """
        from numpy import ones
        ndofs = space.global_dof_count

        return cls(space, coefficients=ones(ndofs))

    @classmethod
    def from_zeros(cls, space):
        """Create a grid function with all coefficients set to one. """
        from numpy import zeros
        ndofs = space.global_dof_count

        return cls(space, coefficients=zeros(ndofs))



# Must be used in jit mode as fun might just be a Python callable and not numba compiled.
@_numba.jit
def _project_function(
    fun,
    grid_data,
    support,
    local2global,
    local_multipliers,
    evaluate_on_element,
    shapeset_evaluate,
    points,
    weights,
    codomain_dimension,
    projections,
):
    """Project a Numba callable onto a grid."""

    number_of_elements = grid_data.elements.shape[1]
    npoints = points.shape[1]
    global_points = _np.empty((3, npoints), dtype=_np.float64)
    fvalues = _np.empty((codomain_dimension, npoints), dtype=projections.dtype)
    fun_result = _np.empty(codomain_dimension, dtype=projections.dtype)
    point = _np.empty(3, dtype=_np.float64)

    for index in range(number_of_elements):
        if not support[index]:
            continue

        element_vals = evaluate_on_element(
            index, shapeset_evaluate, points, grid_data, local_multipliers
        )

        for j in range(3):
            global_points[j] = (
                (1.0 - points[0] - points[1])
                * grid_data.vertices[j, grid_data.elements[0, index]]
                + points[0] * grid_data.vertices[j, grid_data.elements[1, index]]
                + points[1] * grid_data.vertices[j, grid_data.elements[2, index]]
            )

        for j in range(npoints):
            point = global_points[:, j]
            fun(
                point,
                grid_data.normals[index],
                grid_data.domain_indices[index],
                fun_result,
            )
            fvalues[:, j] = fun_result

        projections[local2global[index]] += (
            _np.sum(
                _np.sum(element_vals * _np.expand_dims(fvalues * weights, 1), axis=0),
                axis=1,
            )
            * grid_data.integration_elements[index]
        )