import numpy as np
import scipy as sp
import itertools
from scipy.optimize import minimize
import scipy.constants as const
from scipy.special import hermite
from scipy.linalg import LinAlgError

import scqubits.core.constants as constants
import scqubits.utils.plotting as plot
from scqubits.core.discretization import GridSpec, Grid1d
from scqubits.core.qubit_base import QubitBaseClass
from scqubits.core.storage import WaveFunctionOnGrid
from scqubits.utils.spectrum_utils import standardize_phases, order_eigensystem


#-Flux Qubit using VCHOS 

class FluxQubitVCHOSSqueezing(QubitBaseClass):
    def __init__(self, ECJ, ECg, EJ, ng1, ng2, alpha, flux, kmax, num_exc):
        self.ECJ = ECJ
        self.EJ = EJ
        self.ECg = ECg
        self.ng1 = ng1
        self.ng2 = ng2
        self.alpha = alpha
        self.flux = flux
        self.kmax = kmax
        self.num_exc = num_exc
        self.hGHz = const.h * 10**9
        self.e = np.sqrt(4.0*np.pi*const.alpha)
        self.Z0 = 1. / (2*self.e)**2
        self.Phi0 = 1. / (2*self.e)
        
        self._evec_dtype = np.complex_
        self._default_grid = Grid1d(-6.5*np.pi, 6.5*np.pi, 651)
        
    def build_U_squeezing_operator(self, i):
        a_0 = self.a_operator(0)
        a_1 = self.a_operator(1)
        freq, uvmat = self.squeezing_M_builder(i)
        uvmat = uvmat.T
        dim = uvmat.shape[0]
        u = uvmat[0 : int(dim/2), 0 : int(dim/2)]
        v = uvmat[int(dim/2) : dim, 0 : int(dim/2)]
        u_inv = sp.linalg.inv(u)
        rho = np.matmul(u_inv, v)
        sigma = sp.linalg.logm(u)
        tau = np.matmul(v, u_inv)
        return rho, sigma, tau

    def _define_squeezing_variables(self, rho, rhoprime):
        Xi = self.Xi_matrix()
        Xi_inv = sp.linalg.inv(Xi)
        deltarhoprime = np.matmul(sp.linalg.inv(np.eye(2)-np.matmul(rhoprime, rho)), rhoprime)
        deltarho = np.matmul(sp.linalg.inv(np.eye(2)-np.matmul(rho, rhoprime)), rho)
        deltarhobar = sp.linalg.logm(sp.linalg.inv(np.eye(2)-np.matmul(rhoprime, rho)))
        z = 1j*np.transpose(Xi_inv)/np.sqrt(2.)
        zp = (z+0.5*np.matmul(np.matmul(z, rhoprime), deltarho+deltarho.T)
              +0.5*np.matmul(z, deltarho+deltarho.T))
        zpp = np.matmul(z, rhoprime) + z
        return deltarho, deltarhoprime, deltarhobar, zp, zpp
    
    def _test_squeezing(self, i):
        freq, uvmat = self.squeezing_M_builder(i)
        freq = np.array([2*freq[i] for i in range(len(freq)) if freq[i] > 0])
        dim = uvmat.shape[0]
        u = uvmat[0 : int(dim/2), 0 : int(dim/2)]
        v = uvmat[0 : int(dim/2), int(dim/2) : dim]
        c_0 = np.sum([u[0, i]*self.a_operator(i)+v[0, i]*self.a_operator(i).T
                      for i in range(2)], axis=0)
        c_1 = np.sum([u[1, i]*self.a_operator(i)+v[1, i]*self.a_operator(i).T
                      for i in range(2)], axis=0)
        H_new = np.real((freq[0]*(np.matmul(c_0.T, c_0)+0.5*self._identity())
                + freq[1]*(np.matmul(c_1.T, c_1)+0.5*self._identity())))
        
        Xi = self.Xi_matrix()
        gamma = self.build_gamma_matrix(i)
        gamma_prime = np.matmul(np.transpose(Xi), np.matmul(gamma, Xi))
        zeta = 0.25*(self.Phi0**2 * gamma_prime + self.omegamat())
        eta = 0.25*(self.Phi0**2 * gamma_prime - self.omegamat())
        H_old = np.sum([2*zeta[mu, nu]*np.matmul(self.a_operator(mu).T, self.a_operator(nu))
                        +eta[mu, nu]*np.matmul(self.a_operator(mu).T, self.a_operator(nu).T)
                        +eta[mu, nu]*np.matmul(self.a_operator(mu), self.a_operator(nu))
                        for mu in range(2) for nu in range(2)], axis=0)
        H_old += np.sum([zeta[mu, mu]*np.eye(self.hilbertdim()) for mu in range(2)], axis=0)
        print(H_new[0:5, 0:5])
        print(H_old[0:5, 0:5])
        return 0
    
    def squeezing_M_builder(self, i):
        Xi = self.Xi_matrix()
        dim = Xi.shape[0]
        gamma = self.build_gamma_matrix(i)
        gamma_prime = np.matmul(Xi.T, np.matmul(gamma, Xi))
        zeta = 0.25*(self.Phi0**2 * gamma_prime + self.omegamat())
        eta = 0.25*(self.Phi0**2 * gamma_prime - self.omegamat())
        hmat = np.block([[zeta, -eta],
                         [eta, -zeta]])
        K = np.block([[np.eye(dim), np.zeros((dim, dim))], 
                      [np.zeros((dim, dim)), -np.eye(dim)]])
        eigvals, eigvec = sp.linalg.eig(hmat)
        eigvals, eigvec = self.order_eigensystem_squeezing(np.real(eigvals), eigvec)
        eigvec = eigvec.T #since eigvec represents M.T
        dim = eigvec.shape[0]
        u = eigvec[0 : int(dim/2), 0 : int(dim/2)]
        v = eigvec[int(dim/2) : dim, 0 : int(dim/2)]
        eigvals, eigvec = self.normalize_symplectic_eigensystem_squeezing(eigvals, eigvec)
        assert(np.allclose(np.matmul(eigvec.T, np.matmul(K, eigvec)), K))
        return (eigvals, eigvec)
    
    def order_eigensystem_squeezing(self, eigvals, eigvec):
        """Order eigensystem to have positive eigenvalues followed by negative, in same order"""
        eigval_holder = []
        eigvec_holder = []
        for k, eigval in enumerate(eigvals):
            if eigval > 0:
                eigval_holder.append(eigval)
                eigvec_holder.append(eigvec[:, k])
        eigval_result = np.copy(eigval_holder).tolist()
        eigvec_result = np.copy(eigvec_holder).tolist()
        for k, eigval in enumerate(eigval_holder):
            index = np.argwhere(np.isclose(eigvals, -1.0*eigval))[0, 0]
            eigval_result.append(eigvals[index])
            eigvec_result.append((eigvec[:, index]).tolist())
        return(eigval_result, np.array(eigvec_result))
    
    def normalize_symplectic_eigensystem_squeezing(self, eigvals, eigvec):
        dim = eigvec.shape[0]
        dim2 = int(dim/2)
        for col in range(dim2):
            a = np.sum([eigvec[row, col] for row in range(dim)])
            if a < 0.0:
                eigvec[:, col] *= -1
        A = eigvec[0 : dim2, 0 : dim2]
        B = eigvec[dim2 : dim, 0 : dim2]
        for vec in range(dim2):
            a = 1./np.sqrt(np.sum([A[num, vec]*A[num, vec] - B[num, vec]*B[num, vec] 
                                   for num in range(dim2)]))
            eigvec[:, vec] *= a
        A = eigvec[0 : dim2, 0 : dim2]
        B = eigvec[dim2 : dim, 0 : dim2]
        eigvec[dim2 : dim, dim2 : dim] = A
        eigvec[0 : dim2, dim2 : dim] = B
        return (eigvals, eigvec)
    
    def _normal_ordered_adag_a_exponential(self, x):
        """Expectation is that exp(a_{i}^{\dagger}x_{ij}a_{j}) needs to be normal ordered"""
        expx = sp.linalg.expm(x)
        result = self._identity()
        dim = result.shape[0]
        additionalterm = np.eye(dim)
        k = 1
        while not np.allclose(additionalterm, np.zeros((dim, dim))):
            additionalterm = np.sum([((expx-np.eye(2))[i, j])**(k)
                                     *(sp.special.factorial(k))**(-1)
                                     *np.matmul(np.linalg.matrix_power(self.a_operator(i).T, k), 
                                                np.linalg.matrix_power(self.a_operator(j), k))
                                     for i in range(2) for j in range(2)], axis=0)
            result += additionalterm
            k += 1
        return result
        
    def potential(self, phiarray):
        """
        Flux qubit potential evaluated at `phi1` and `phi2` 
        """
        phi1 = phiarray[0]
        phi2 = phiarray[1]
        return (-self.EJ*np.cos(phi1) -self.EJ*np.cos(phi2)
                -self.EJ*self.alpha*np.cos(phi1-phi2+2.0*np.pi*self.flux))
    
    def build_capacitance_matrix(self):
        """Return the capacitance matrix"""
        Cmat = np.zeros((2, 2))
                
        CJ = self.e**2 / (2.*self.ECJ)
        Cg = self.e**2 / (2.*self.ECg)
        
        Cmat[0, 0] = CJ + self.alpha*CJ + Cg
        Cmat[1, 1] = CJ + self.alpha*CJ + Cg
        Cmat[0, 1] = -self.alpha*CJ
        Cmat[1, 0] = -self.alpha*CJ
        
        return Cmat
    
    def build_EC_matrix(self):
        """Return the charging energy matrix"""
        Cmat = self.build_capacitance_matrix()
        return  0.5 * self.e**2 * sp.linalg.inv(Cmat)
    
    def build_gamma_matrix(self, i):
        """
        Return linearized potential matrix
        
        Note that we must divide by Phi_0^2 since Ej/Phi_0^2 = 1/Lj,
        or one over the effective impedance of the junction.
        
        """
        gmat = np.zeros((2,2))
        
        local_or_global_min = self.sorted_minima()[i]
        phi1_min = local_or_global_min[0]
        phi2_min = local_or_global_min[1]
        
        gamma = self.EJ / self.Phi0**2
        
        gmat[0, 0] = gamma*np.cos(phi1_min) + self.alpha*gamma*np.cos(2*np.pi*self.flux 
                                                                      + phi1_min - phi2_min)
        gmat[1, 1] = gamma*np.cos(phi2_min) + self.alpha*gamma*np.cos(2*np.pi*self.flux 
                                                                      + phi1_min - phi2_min)
        gmat[0, 1] = gmat[1, 0] = -self.alpha*gamma*np.cos(2*np.pi*self.flux + phi1_min - phi2_min)
        
        return gmat
    
    def omegamat(self):
        """Return a diagonal matrix of the normal mode frequencies of the global min """
        Cmat = self.build_capacitance_matrix()
        gmat = self.build_gamma_matrix(0)
        
        omegasq, eigvec = sp.linalg.eigh(gmat, b=Cmat)
        return np.diag(np.sqrt(omegasq))
            
    def Xi_matrix(self):
        """Construct the Xi matrix, encoding the oscillator lengths of each dimension"""
        Cmat = self.build_capacitance_matrix()
        gmat = self.build_gamma_matrix(0)
        
        omegasq, eigvec = sp.linalg.eigh(gmat, b=Cmat)
        
        Ximat = np.array([eigvec[:,i]*np.sqrt(np.sqrt(1./omegasq[i]))
                          * np.sqrt(1./self.Z0) for i in range(Cmat.shape[0])])
        
        # Note that the actual Xi matrix is the transpose of above, 
        # due to list comprehension syntax reasons. Here we are 
        # asserting that \Xi^T C \Xi = \Omega^{-1}/Z0
        assert(np.allclose(np.matmul(Ximat, np.matmul(Cmat, np.transpose(Ximat))),
                              sp.linalg.inv(np.diag(np.sqrt(omegasq)))/self.Z0))

        return np.transpose(Ximat)
    
    def a_operator(self, mu):
        """Return the lowering operator associated with the xth d.o.f. in the full Hilbert space"""
        a = np.array([np.sqrt(num) for num in range(1, self.num_exc + 1)])
        a_mat = np.diag(a,k=1)
        return self._full_o([a_mat], [mu])
                    
    def normal_ordered_exp_i_phi_operator(self, x):
        """Return the normal ordered e^{i\phi_x} operator, expressed using ladder ops"""
        Xi_mat = self.Xi_matrix()
        return(np.exp(-.25*np.dot(Xi_mat[x, :], np.transpose(Xi_mat)[:, x]))
               *np.matmul(self.matrix_exp(1j*np.sum([Xi_mat[x,mu]*self.a_operator(mu).T 
                                            for mu in range(2)], axis=0)/np.sqrt(2)), 
                          self.matrix_exp(1j*np.sum([Xi_mat[x,mu]*self.a_operator(mu) 
                                            for mu in range(2)], axis=0)/np.sqrt(2))))
    
    def normal_ordered_exp_i_phix_mi_phiy(self, x, y):
        """Return the normal ordered e^{i\phi_x-i\phi_y} operator, expressed using ladder ops"""
        Xi_mat = self.Xi_matrix()
        a_dag_prod = np.matmul(self.matrix_exp(1j*np.sum([Xi_mat[x,mu]*self.a_operator(mu).T 
                                                          for mu in range(2)], axis=0)/np.sqrt(2)),
                               self.matrix_exp(-1j*np.sum([Xi_mat[y,mu]*self.a_operator(mu).T 
                                                           for mu in range(2)], axis=0)/np.sqrt(2)))
        a_prod = np.matmul(self.matrix_exp(1j*np.sum([Xi_mat[x,mu]*self.a_operator(mu)
                                                      for mu in range(2)], axis=0)/np.sqrt(2)),
                           self.matrix_exp(-1j*np.sum([Xi_mat[y,mu]*self.a_operator(mu)
                                                       for mu in range(2)], axis=0)/np.sqrt(2)))
        return(np.matmul(a_dag_prod, a_prod)
               *np.exp(-.25*np.dot(Xi_mat[x, :], np.transpose(Xi_mat)[:, x]))
               *np.exp(-.25*np.dot(Xi_mat[y, :], np.transpose(Xi_mat)[:, y]))
               *np.exp(0.5*np.dot(Xi_mat[y, :], np.transpose(Xi_mat)[:, x])))
        
    def _identity(self):
        return(np.identity(self.hilbertdim(), dtype=np.complex_))
        
    def delta_inv_matrix(self):
        """"Construct the delta inverse matrix, as described in David's notes """
        Xi_T_inv = np.transpose(sp.linalg.inv(self.Xi_matrix()))
        Xi_inv = sp.linalg.inv(self.Xi_matrix())
        return np.matmul(Xi_T_inv,Xi_inv)
        
    def matrix_exp(self, matrix):
        return (sp.linalg.expm(matrix))
    
    def _exp_a_operators(self):
        """Return the exponential of the a operators with appropriate coefficients for efficiency purposes """
        Xi = self.Xi_matrix()
        Xi_inv_T = sp.linalg.inv(Xi).T
        exp_a_00 = self.matrix_exp(2.0*np.pi*Xi_inv_T[0, 0]*self.a_operator(0)/np.sqrt(2.0))
        exp_a_10 = self.matrix_exp(2.0*np.pi*Xi_inv_T[1, 0]*self.a_operator(0)/np.sqrt(2.0))
        exp_a_01 = self.matrix_exp(2.0*np.pi*Xi_inv_T[0, 1]*self.a_operator(1)/np.sqrt(2.0))
        exp_a_11 = self.matrix_exp(2.0*np.pi*Xi_inv_T[1, 1]*self.a_operator(1)/np.sqrt(2.0))
        return(exp_a_00, exp_a_10, exp_a_01, exp_a_11)
    
    def _exp_a_operators_minima_diff(self, minima_diff):
        Xi_inv_T = sp.linalg.inv(self.Xi_matrix()).T
        exp_min_diff = self.matrix_exp(np.sum([minima_diff[x]*Xi_inv_T[x, mu]*self.a_operator(mu)
                                               for x in range(2) for mu in range(2)], axis=0)/np.sqrt(2.0))
        return(exp_min_diff)
    
    def _V_operator_helper_using_exp_a_operators(self, phi, exp_a_list):
        """Return the periodic continuation part of the V operator without 
        additional calls to matrix_exp and without the prefactor """
        jkvals = phi/(2.0*np.pi)
        j0 = int(jkvals[0])
        j1 = int(jkvals[1])
                
        V00_op = np.linalg.matrix_power(exp_a_list[0], j0)
        V01_op = np.linalg.matrix_power(exp_a_list[2], j0)
        V0_op = np.matmul(V00_op, V01_op)
        
        V10_op = np.linalg.matrix_power(exp_a_list[1], j1)
        V11_op = np.linalg.matrix_power(exp_a_list[3], j1)
        V1_op = np.matmul(V10_op, V11_op)
        
        return(np.matmul(V0_op, V1_op))
            
    def V_operator(self, phi):
        """Return the V operator """
        phi_delta_phi = np.matmul(phi,np.matmul(self.delta_inv_matrix(),phi))
        prefactor = np.exp(-.125 * phi_delta_phi)
        phi_Xi_inv = np.matmul(phi,np.transpose(sp.linalg.inv(self.Xi_matrix())))
        phi_Xi_inv_a = np.sum([phi_Xi_inv[mu]*self.a_operator(mu) for mu in range(2)], axis=0)
        op = self.matrix_exp((1./np.sqrt(2.))*phi_Xi_inv_a)
        return prefactor * op
    
    def V_operator_full(self, minima_diff, phik, exp_min_diff, exp_a_list, delta_inv):
        """Return the V operator using the more efficient methods """
        delta_phi_kpm = phik+minima_diff
        phi_delta_phi = np.matmul(delta_phi_kpm,np.matmul(delta_inv,delta_phi_kpm))
        prefactor = np.exp(-.125 * phi_delta_phi)
        V_op_phik = self._V_operator_helper_using_exp_a_operators(phik, exp_a_list)
        V_op = prefactor * np.matmul(exp_min_diff, V_op_phik)
        return V_op
        
    def _unordered_kineticmat(self):
        """
        Generally have not found this to be helpful, as it 
        requires an extraordinary number of excitations to converge 
        even for the 0, 0 element
        """
        Xi = self.Xi_matrix()
        Xi_inv = sp.linalg.inv(Xi)
        EC_mat = self.build_EC_matrix()
        EC_mat_t = np.matmul(Xi_inv,np.matmul(EC_mat,np.transpose(Xi_inv)))
        dim = self.hilbertdim()
        minima_list = self.sorted_minima()
        kinetic_mat = np.zeros((dim,dim), dtype=np.complex128)
        nglist = np.array([self.ng1, self.ng2])
        for m, minima_m in enumerate(minima_list):
            if m == 0: #At the global minimum, no squeezing required
                rho = np.zeros((2, 2)) # 2 d.o.f.
                sigma = np.zeros((2, 2))
                tau = np.zeros((2, 2)) 
            else:
                rho, sigma, tau = self.build_U_squeezing_operator(m)
            R = sp.linalg.expm(np.sum([-0.5*rho[i, j]*np.matmul(self.a_operator(i).T, self.a_operator(j).T)
                                       for i in range(2) for j in range(2)], axis=0))
            S = sp.linalg.expm(np.sum([-sigma[i, j]*np.matmul(self.a_operator(i).T, self.a_operator(j))
                                       for i in range(2) for j in range(2)], axis=0))
            T = sp.linalg.expm(np.sum([0.5*tau[i, j]*np.matmul(self.a_operator(i), self.a_operator(j))
                                       for i in range(2) for j in range(2)], axis=0))
            
            Udag = np.exp(-0.5*np.trace(sigma))*np.matmul(R, np.matmul(S, T)).T
            for p, minima_p in enumerate(minima_list):
                if p == 0: #At the global minimum, no squeezing required
                    rhop = np.zeros((2, 2)) # 2 d.o.f.
                    sigmap = np.zeros((2, 2))
                    taup = np.zeros((2, 2)) 
                else:
                    rhop, sigmap, taup = self.build_U_squeezing_operator(p)
                Rp = sp.linalg.expm(np.sum([-0.5*rhop[i, j]*np.matmul(self.a_operator(i).T, self.a_operator(j).T)
                                           for i in range(2) for j in range(2)], axis=0))
                Sp = sp.linalg.expm(np.sum([-sigmap[i, j]*np.matmul(self.a_operator(i).T, self.a_operator(j))
                                           for i in range(2) for j in range(2)], axis=0))
                Tp = sp.linalg.expm(np.sum([0.5*taup[i, j]*np.matmul(self.a_operator(i),  self.a_operator(j))
                                           for i in range(2) for j in range(2)], axis=0))
            
                Uprime = np.exp(-0.5*np.trace(sigmap))*np.matmul(Rp, np.matmul(Sp, Tp))
                klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=2)
                jkvals = next(klist,-1)
                while jkvals != -1:
                    phik = 2.0*np.pi*np.array([jkvals[0],jkvals[1]])
                    delta_phi_kpm = phik-(minima_m-minima_p)
                    minima_diff = minima_p-minima_m
                    
                    right_op = sp.linalg.expm(np.sum([-(1/np.sqrt(2.))*(phik+minima_p)[x]*np.transpose(Xi_inv)[x, mu]
                                                     *(self.a_operator(mu)-self.a_operator(mu).T)
                                                     for x in range(2) for mu in range(2)], axis=0))
                    left_op = sp.linalg.expm(np.sum([(1/np.sqrt(2.))*(minima_m)[x]*np.transpose(Xi_inv)[x, mu]
                                                     *(self.a_operator(mu)-self.a_operator(mu).T)
                                                     for x in range(2) for mu in range(2)], axis=0))
                    kinetic_temp = 0.0
                    for mu in range(2):
                        for nu in range(2):
                            kinetic_temp += -2.0*EC_mat_t[mu, nu]*(np.matmul(self.a_operator(mu)-self.a_operator(mu).T,
                                                                             self.a_operator(nu)-self.a_operator(nu).T))
                    kinetic_temp = (np.exp(-1j*np.dot(nglist, delta_phi_kpm))*
                                    np.matmul(np.matmul(Udag, left_op), 
                                              np.matmul(kinetic_temp, np.matmul(right_op, Uprime))))
                    num_exc_tot = self.hilbertdim()
                    kinetic_mat[m*num_exc_tot : m*num_exc_tot + num_exc_tot, 
                                p*num_exc_tot : p*num_exc_tot + num_exc_tot] += kinetic_temp
                    jkvals = next(klist,-1)
                    
        return kinetic_mat   
    
    def build_normal_ordered_squeezing_ops(self, m, p):
        if m == 0: #At the global minimum, no squeezing required
            rho = np.zeros((2, 2)) # 2 d.o.f.
            sigma = np.zeros((2, 2))
            tau = np.zeros((2, 2)) 
        else:
            rho, sigma, tau = self.build_U_squeezing_operator(m)
        if p == 0:
            rhoprime = np.zeros((2, 2)) # 2 d.o.f.
            sigmaprime = np.zeros((2, 2))
            tauprime = np.zeros((2, 2)) 
        elif p == m:
            rhoprime = np.copy(rho)
            sigmaprime = np.copy(sigma)
            tauprime = np.copy(tau)
        else:
            rhoprime, sigmaprime, tauprime = self.build_U_squeezing_operator(p)
            
        deltarho, deltarhoprime, deltarhobar, zp, zpp = self._define_squeezing_variables(rho, rhoprime)
        
        expsigma = sp.linalg.expm(-sigma)
        expsigmaprime = sp.linalg.expm(-sigmaprime)
        expdeltarhobar = sp.linalg.expm(deltarhobar)
                
        prefactor_adag_adag = 0.5*(tau.T-np.matmul(expsigma.T, np.matmul(deltarhoprime, expsigma)))
        prefactor_a_a = 0.5*(tauprime-np.matmul(expsigmaprime.T, np.matmul(deltarho, expsigmaprime)))
        prefactor_adag_a = sp.linalg.logm(np.matmul(expsigma.T, np.matmul(expdeltarhobar, expsigmaprime)))
                
        exp_adag_adag = sp.linalg.expm(np.sum([prefactor_adag_adag[i, j]
                                               *np.matmul(self.a_operator(i).T, 
                                                          self.a_operator(j).T)
                                               for i in range(2) for j in range(2)], axis=0))
        exp_a_a = sp.linalg.expm(np.sum([prefactor_a_a[i, j]
                                         *np.matmul(self.a_operator(i), 
                                                    self.a_operator(j))
                                         for i in range(2) for j in range(2)], axis=0))
        exp_adag_a = self._normal_ordered_adag_a_exponential(prefactor_adag_a)
        
        return (exp_adag_adag, exp_a_a, exp_adag_a, rho, 
                rhoprime, sigma, sigmaprime, deltarho, deltarhobar, zp, zpp)
        
    
    def kineticmat(self):
        """Return the kinetic part of the hamiltonian"""
        Xi = self.Xi_matrix()
        Xi_inv = sp.linalg.inv(Xi)
        delta_inv = np.matmul(np.transpose(Xi_inv), Xi_inv)
        num_exc_tot = self.hilbertdim()
        EC_mat = self.build_EC_matrix()
        EC_mat_t = np.matmul(Xi_inv,np.matmul(EC_mat,np.transpose(Xi_inv)))
        dim = self.matrixdim()
        minima_list = self.sorted_minima()
        kinetic_mat = np.zeros((dim,dim), dtype=np.complex128)
        nglist = np.array([self.ng1, self.ng2])
        for m, minima_m in enumerate(minima_list):
            for p, minima_p in enumerate(minima_list):
                (exp_adag_adag, exp_a_a, exp_adag_a, 
                 rho, rhoprime, sigma, sigmaprime,
                 deltarho, deltarhobar, zp, zpp) = self.build_normal_ordered_squeezing_ops(m, p)
                klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=2)
                jkvals = next(klist,-1)
                while jkvals != -1:
                    phik = 2.0*np.pi*np.array([jkvals[0],jkvals[1]])
                    delta_phi_kpm = phik-(minima_m-minima_p)
                    minima_diff = minima_p-minima_m
                    
                    x = np.matmul(delta_phi_kpm, Xi_inv.T)/np.sqrt(2.)
                    y = -x
                    z = 1j*Xi_inv.T/np.sqrt(2.)
                    scale = 1./np.sqrt(sp.linalg.det(np.eye(2)-np.matmul(rho, rhoprime)))
                    yrhop = np.matmul(y, rhoprime)
                    expsdrb = np.matmul(sp.linalg.expm(-sigma).T, sp.linalg.expm(deltarhobar))
                    expsigma = sp.linalg.expm(-sigma)
                    expsigmaprime = sp.linalg.expm(-sigmaprime)
                    alpha = scale * np.exp(-0.5*(np.matmul(y, yrhop) + np.matmul(x-yrhop, np.matmul(deltarho, x-yrhop))))
                    deltarhopp = 0.5*np.matmul(x-yrhop, deltarho+deltarho.T)
                    
                    epsilon = (-np.matmul(z, np.matmul(rhoprime, deltarhopp) - yrhop + deltarhopp)
                               - (1j/2.)*np.matmul(Xi_inv.T, np.matmul(Xi_inv, delta_phi_kpm)))
                                        
                    prefactor_adag = np.matmul(x-yrhop, np.matmul(sp.linalg.expm(deltarhobar).T, expsigma))
                    prefactor_a = np.matmul(y-deltarhopp, expsigmaprime)
                    
                    exp_adag = sp.linalg.expm(np.sum([prefactor_adag[i]*self.a_operator(i).T
                                                      for i in range(2)], axis=0))
                    exp_a = sp.linalg.expm(np.sum([prefactor_a[i]*self.a_operator(i)
                                                   for i in range(2)], axis=0))

                    kinetic_temp = np.sum([+4*np.matmul(exp_adag_a, np.matmul(self.a_operator(mu),
                                                                              self.a_operator(nu)))
                                           *np.matmul(np.matmul(expsigmaprime.T, zp.T), 
                                                      np.matmul(EC_mat , np.matmul(zp, expsigmaprime)))[mu, nu]
                                           -8*np.matmul(self.a_operator(mu).T, np.matmul(exp_adag_a, self.a_operator(nu)))
                                           *np.matmul(np.matmul(expsdrb, zpp.T), 
                                                      np.matmul(EC_mat, np.matmul(zp, expsigmaprime)))[mu, nu]
                                           +4*np.matmul(self.a_operator(mu).T, np.matmul(self.a_operator(nu).T, exp_adag_a))
                                           *np.matmul(np.matmul(expsdrb, zpp.T), 
                                                      np.matmul(EC_mat , np.matmul(zpp, expsdrb.T)))[mu, nu]
                                           -4*exp_adag_a*np.matmul(zpp.T, np.matmul(EC_mat, zp))[mu, nu]
                                           -8*np.matmul(exp_adag_a, self.a_operator(mu))
                                           *epsilon[nu]*np.matmul(np.matmul(EC_mat[nu, :], zp), expsigmaprime[:, mu])
                                           +8*np.matmul(self.a_operator(nu).T, exp_adag_a)
                                           *epsilon[mu]*np.matmul(np.matmul(EC_mat[mu, :], zpp), 
                                                                  np.transpose(expsdrb)[:, nu])
                                           for mu in range(2) for nu in range(2)], axis = 0)
                    
                    kinetic_temp += 4*exp_adag_a*np.matmul(epsilon, np.matmul(EC_mat, epsilon))
                                        
                    kinetic_temp = (alpha * np.exp(-1j*np.dot(nglist, delta_phi_kpm)) 
                                    * np.exp(-0.5*np.trace(sigma)-0.5*np.trace(sigmaprime)) #from U, U'
                                    * np.exp(-0.25*np.matmul(np.matmul(delta_phi_kpm, Xi_inv.T), 
                                                             np.matmul(Xi_inv, delta_phi_kpm))) #from V ops
                                    * np.matmul(np.matmul(exp_adag_adag, exp_adag), 
                                                np.matmul(kinetic_temp, np.matmul(exp_a, exp_a_a))))
                    
                    kinetic_mat[m*num_exc_tot : m*num_exc_tot + num_exc_tot, 
                                p*num_exc_tot : p*num_exc_tot + num_exc_tot] += kinetic_temp
                    
                    jkvals = next(klist,-1)
                                           
        return kinetic_mat
    
    def potentialmat(self):
        """Return the potential part of the hamiltonian"""
        Xi = self.Xi_matrix()
        Xi_inv = sp.linalg.inv(Xi)
        delta_inv = np.matmul(np.transpose(Xi_inv), Xi_inv)
        dim = self.matrixdim()
        num_exc_tot = self.hilbertdim()
        potential_mat = np.zeros((dim,dim), dtype=np.complex128)
        minima_list = self.sorted_minima()
        exp_i_phi_0 = self.normal_ordered_exp_i_phi_operator(0)
        exp_i_phi_1 = self.normal_ordered_exp_i_phi_operator(1)
        exp_i_phi_0_m1 = self.normal_ordered_exp_i_phix_mi_phiy(0, 1)
        exp_a_list = self._exp_a_operators()
        nglist = np.array([self.ng1, self.ng2])
        for m, minima_m in enumerate(minima_list):
            for p, minima_p in enumerate(minima_list):
                (exp_adag_adag, exp_a_a, exp_adag_a, 
                 rho, rhoprime, sigma, sigmaprime,
                 deltarho, deltarhobar, _, _) = self.build_normal_ordered_squeezing_ops(m, p)
                klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=2)
                jkvals = next(klist,-1)
                while jkvals != -1:
                    phik = 2.0*np.pi*np.array([jkvals[0],jkvals[1]])
                    delta_phi_kpm = phik-(minima_m-minima_p) 
                    phibar_kpm = 0.5*(phik+(minima_m+minima_p))                     
                    for num in range(2): #summing over potential terms cos(\phi_x)
                        x = (np.matmul(delta_phi_kpm, Xi_inv.T) + 1j*Xi[num, :])/np.sqrt(2.)
                        y = (-np.matmul(delta_phi_kpm, Xi_inv.T) + 1j*Xi[num, :])/np.sqrt(2.)
                    
                        potential_temp = (-0.5*self.EJ
                                          *self._potential_squeezing_helper(x, y, exp_adag_a, rho, rhoprime, 
                                                                            deltarho, deltarhobar, 
                                                                            sigma, sigmaprime)
                                          *np.exp(1j*phibar_kpm[num])
                                          *np.exp(-.25*np.dot(Xi[num, :], np.transpose(Xi)[:, num]))
                                          -0.5*self.EJ
                                          *self._potential_squeezing_helper(x.conjugate(), y.conjugate(), 
                                                                            exp_adag_a, rho, rhoprime, deltarho, 
                                                                            deltarhobar, sigma, 
                                                                            sigmaprime)
                                          *np.exp(-1j*phibar_kpm[num])
                                          *np.exp(-.25*np.dot(Xi[num, :], np.transpose(Xi)[:, num])))
                        
                        # This is adding the identity term for each of \cos(\phi_x)
                        #####
                        just_trans_x = (x + x.conjugate())/2
                        just_trans_y = (y + y.conjugate())/2
                        potential_temp += self.EJ*self._potential_squeezing_helper(just_trans_x, just_trans_y, 
                                                                           exp_adag_a, rho, rhoprime, 
                                                                           deltarho, deltarhobar, 
                                                                           sigma, sigmaprime)
                        #####
                        
                        potential_temp = (np.exp(-1j*np.dot(nglist, delta_phi_kpm)) 
                                          * np.exp(-0.5*np.trace(sigma)-0.5*np.trace(sigmaprime))
                                          * np.exp(-0.25*np.matmul(np.matmul(delta_phi_kpm, Xi_inv.T), 
                                                   np.matmul(Xi_inv, delta_phi_kpm)))
                                          * np.matmul(np.matmul(exp_adag_adag, potential_temp), exp_a_a))
                        
                        potential_mat[m*num_exc_tot:m*num_exc_tot+num_exc_tot, 
                                      p*num_exc_tot:p*num_exc_tot+num_exc_tot] += potential_temp
                            
                    x = (np.matmul(delta_phi_kpm, Xi_inv.T) + 1j*(Xi[0, :]-Xi[1,:]))/np.sqrt(2.)
                    y = (-np.matmul(delta_phi_kpm, Xi_inv.T) + 1j*(Xi[0, :]-Xi[1,:]))/np.sqrt(2.)
                    
                    potential_temp = (-0.5*self.alpha*self.EJ
                                      *self._potential_squeezing_helper(x, y, exp_adag_a, rho, rhoprime, 
                                                                        deltarho, deltarhobar, 
                                                                        sigma, sigmaprime)
                                      *np.exp(1j*2.0*np.pi*self.flux)
                                      *np.exp(1j*phibar_kpm[0])
                                      *np.exp(-1j*phibar_kpm[1])
                                      -0.5*self.alpha*self.EJ
                                      *self._potential_squeezing_helper(x.conjugate(), y.conjugate(), 
                                                                        exp_adag_a, rho, rhoprime, deltarho, 
                                                                        deltarhobar, sigma, sigmaprime)
                                      *np.exp(-1j*2.0*np.pi*self.flux)
                                      *np.exp(-1j*phibar_kpm[0])
                                      *np.exp(1j*phibar_kpm[1])
                                      )
                    potential_temp *= (np.exp(-.25*np.dot(Xi[0, :], np.transpose(Xi)[:, 0]))
                                       *np.exp(-.25*np.dot(Xi[1, :], np.transpose(Xi)[:, 1]))
                                       *np.exp(0.5*np.dot(Xi[1, :], np.transpose(Xi)[:, 0])))
                    
                    # This is adding the identity term for \cos(\phi_1-\phi2-2*pi*f)
                    #####
                    just_trans_x = (x + x.conjugate())/2
                    just_trans_y = (y + y.conjugate())/2
                    potential_temp += self.alpha*self.EJ*self._potential_squeezing_helper(just_trans_x, just_trans_y, 
                                                                       exp_adag_a, rho, rhoprime, 
                                                                       deltarho, deltarhobar, 
                                                                       sigma, sigmaprime)
                    #####

                    potential_temp = (np.exp(-1j*np.dot(nglist, delta_phi_kpm)) 
                                      * np.exp(-0.5*np.trace(sigma)-0.5*np.trace(sigmaprime))
                                      * np.exp(-0.25*np.matmul(np.matmul(delta_phi_kpm, Xi_inv.T), 
                                                               np.matmul(Xi_inv, delta_phi_kpm)))
                                      * np.matmul(np.matmul(exp_adag_adag, potential_temp), exp_a_a))
                    
                    potential_mat[m*num_exc_tot:m*num_exc_tot+num_exc_tot, 
                                  p*num_exc_tot:p*num_exc_tot+num_exc_tot] += potential_temp
            
                    jkvals = next(klist,-1)
                        
        return potential_mat       
    
    def _potential_squeezing_helper(self, x, y, exp_adag_a, rho, rhoprime, 
                                    deltarho, deltarhobar, sigma, sigmaprime):
        expdeltarhobar = sp.linalg.expm(deltarhobar)
        expsigma = sp.linalg.expm(-sigma)
        expsigmaprime = sp.linalg.expm(-sigmaprime)
        scale = 1./np.sqrt(sp.linalg.det(np.eye(2)-np.matmul(rho, rhoprime)))
        yrhop = np.matmul(y, rhoprime)
        alpha = scale * np.exp(-0.5*(np.matmul(y, yrhop) + np.matmul(x-yrhop, np.matmul(deltarho, x-yrhop))))
        deltarhopp = 0.5*np.matmul(x-np.matmul(rhoprime, y), deltarho+deltarho.T)
                    
        prefactor_adag = np.matmul(x-np.matmul(y, rhoprime), np.matmul(expdeltarhobar.T, expsigma))
        prefactor_a = np.matmul(y-deltarhopp, expsigmaprime)
            
        exp_adag = sp.linalg.expm(np.sum([prefactor_adag[i]*self.a_operator(i).T
                                          for i in range(2)], axis=0))
        exp_a = sp.linalg.expm(np.sum([prefactor_a[i]*self.a_operator(i)
                                       for i in range(2)], axis=0))
        return alpha*np.matmul(exp_adag, np.matmul(exp_adag_a, exp_a))
                                                                          
    def hamiltonian(self):
        """Construct the Hamiltonian"""
        return (self.kineticmat() + self.potentialmat())
        
    def inner_product(self):
        """Return the inner product matrix, which is nontrivial with VCHOS states"""
        Xi = self.Xi_matrix()
        Xi_inv = sp.linalg.inv(Xi)
        delta_inv = np.matmul(np.transpose(Xi_inv), Xi_inv)
        dim = self.matrixdim()
        num_exc_tot = self.hilbertdim()
        inner_product_mat = np.zeros((dim,dim), dtype=np.complex128)
        minima_list = self.sorted_minima()
        nglist = np.array([self.ng1, self.ng2])
        for m, minima_m in enumerate(minima_list):
            for p, minima_p in enumerate(minima_list):
                (exp_adag_adag, exp_a_a, exp_adag_a, 
                 rho, rhoprime, sigma, sigmaprime,
                 deltarho, deltarhobar, _, _) = self.build_normal_ordered_squeezing_ops(m, p)
                klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=2)
                jkvals = next(klist,-1)
                while jkvals != -1:
                    phik = 2.0*np.pi*np.array([jkvals[0],jkvals[1]])
                    delta_phi_kpm = phik-(minima_m-minima_p) 
                    minima_diff = minima_p-minima_m
                            
                    x = np.matmul(delta_phi_kpm, Xi_inv.T)/np.sqrt(2.)
                    y = -np.matmul(delta_phi_kpm, Xi_inv.T)/np.sqrt(2.)
                    
                    scale = 1./np.sqrt(sp.linalg.det(np.eye(2)-np.matmul(rho, rhoprime)))
                    yrhop = np.matmul(y, rhoprime)
                    alpha = scale * np.exp(-0.5*(np.matmul(y, yrhop) + np.matmul(x-yrhop, np.matmul(deltarho, x-yrhop))))
                    deltarhopp = 0.5*np.matmul(x-yrhop, deltarho+deltarho.T)
                
                    prefactor_adag = np.matmul(x-yrhop, np.matmul(sp.linalg.expm(deltarhobar).T, 
                                                                  sp.linalg.expm(-sigma)))
                    prefactor_a = np.matmul(y-deltarhopp, sp.linalg.expm(-sigmaprime))
                    
                    exp_adag = sp.linalg.expm(np.sum([prefactor_adag[i]*self.a_operator(i).T
                                                      for i in range(2)], axis=0))
                    exp_a = sp.linalg.expm(np.sum([prefactor_a[i]*self.a_operator(i)
                                                   for i in range(2)], axis=0))

                    inner_temp = (alpha * np.exp(-1j*np.dot(nglist, delta_phi_kpm)) 
                                  * np.exp(-0.5*np.trace(sigma)-0.5*np.trace(sigmaprime))
                                  * np.exp(-0.25*np.matmul(np.matmul(delta_phi_kpm, Xi_inv.T), 
                                                           np.matmul(Xi_inv, delta_phi_kpm)))
                                  * np.matmul(np.matmul(exp_adag_adag, np.matmul(exp_adag, exp_adag_a)), 
                                              np.matmul(exp_a, exp_a_a)))
                    
                    inner_product_mat[m*num_exc_tot:m*num_exc_tot+num_exc_tot, 
                                      p*num_exc_tot:p*num_exc_tot+num_exc_tot] += inner_temp
                    jkvals = next(klist,-1)
                        
        return inner_product_mat
    
    def _check_if_new_minima(self, new_minima, minima_holder):
        """
        Helper function for find_minima, checking if minima is
        already represented in minima_holder. If so, 
        _check_if_new_minima returns False.
        """
        new_minima_bool = True
        for minima in minima_holder:
            diff_array = minima - new_minima
            diff_array_reduced = np.array([np.mod(x,2*np.pi) for x in diff_array])
            elem_bool = True
            for elem in diff_array_reduced:
                # if every element is zero or 2pi, then we have a repeated minima
                elem_bool = elem_bool and (np.allclose(elem,0.0,atol=1e-3) 
                                           or np.allclose(elem,2*np.pi,atol=1e-3))
            if elem_bool:
                new_minima_bool = False
                break
        return new_minima_bool
    
    def _ramp(self, k, minima_holder):
        """
        Helper function for find_minima, performing the ramp that
        is described in Sec. III E of [0]
        
        [0] PRB ...
        """
        guess = np.array([1.15*2.0*np.pi*k/3.0,2.0*np.pi*k/3.0])
        result = minimize(self.potential, guess)
        new_minima = self._check_if_new_minima(result.x, minima_holder)
        if new_minima:
            minima_holder.append(np.array([np.mod(elem,2*np.pi) for elem in result.x]))
        return (minima_holder, new_minima)
    
    def find_minima(self):
        """
        Index all minima in the variable space of phi1 and phi2
        """
        minima_holder = []
        if self.flux == 0.5:
            guess = np.array([0.15,0.1])
        else:
            guess = np.array([0.0,0.0])
        result = minimize(self.potential,guess)
        minima_holder.append(np.array([np.mod(elem,2*np.pi) for elem in result.x]))
        k = 0
        for k in range(1,4):
            (minima_holder, new_minima_positive) = self._ramp(k, minima_holder)
            (minima_holder, new_minima_negative) = self._ramp(-k, minima_holder)
            if not (new_minima_positive and new_minima_negative):
                break
        return(minima_holder)
    
    def sorted_minima(self):
        """Sort the minima based on the value of the potential at the minima """
        minima_holder = self.find_minima()
        value_of_potential = np.array([self.potential(minima_holder[x]) 
                                       for x in range(len(minima_holder))])
        sorted_minima_holder = np.array([x for _, x in 
                                         sorted(zip(value_of_potential, minima_holder))])
        return sorted_minima_holder
    
    def matrixdim(self):
        """Return N if the size of the Hamiltonian matrix is NxN"""
        return len(self.sorted_minima())*(self.num_exc+1)**2
    
    def hilbertdim(self):
        """Return Hilbert space dimension."""
        return (self.num_exc+1)**2
    
    def wavefunction(self, esys=None, which=0, phi_grid=None):
        """
        Return a flux qubit wave function in phi1, phi2 basis

        Parameters
        ----------
        esys: ndarray, ndarray
            eigenvalues, eigenvectors
        which: int, optional
            index of desired wave function (default value = 0)
        phi_range: tuple(float, float), optional
            used for setting a custom plot range for phi
        phi_count: int, optional
            number of points to use on grid in each direction

        Returns
        -------
        WaveFunctionOnGrid object
        """
        evals_count = max(which + 1, 3)
        if esys is None:
            _, evecs = self.eigensys(evals_count)
        else:
            _, evecs = esys
        phi_grid = self._try_defaults(phi_grid)
        phi_vec = phi_grid.make_linspace()
        zeta_vec = phi_grid.make_linspace()
#        phi_vec = np.linspace(phi_grid.min_val, phi_grid.max_val, 10)
        
        minima_list = self.sorted_minima()
        num_minima = len(minima_list)
        dim = self.hilbertdim()
        num_deg_freedom = (self.num_exc+1)**2
        
        Xi = self.Xi_matrix()
        Xi_inv = sp.linalg.inv(Xi)
        norm = np.sqrt(np.abs(np.linalg.det(Xi)))**(-1)
        
        state_amplitudes_list = []
        
        phi1_phi2_outer = np.outer(phi_vec, phi_vec)
        wavefunc_amplitudes = np.zeros_like(phi1_phi2_outer)
        
        for i, minimum in enumerate(minima_list):
            klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=2)
            jkvals = next(klist,-1)
            while jkvals != -1:
                phik = 2.0*np.pi*np.array([jkvals[0],jkvals[1]])
                phi1_s1_arg = (Xi_inv[0,0]*phik[0] - Xi_inv[0,0]*minimum[0])
                phi2_s1_arg = (Xi_inv[0,1]*phik[1] - Xi_inv[0,1]*minimum[1])
                phi1_s2_arg = (Xi_inv[1,0]*phik[0] - Xi_inv[1,0]*minimum[0])
                phi2_s2_arg = (Xi_inv[1,1]*phik[1] - Xi_inv[1,1]*minimum[1])
                state_amplitudes = np.real(np.reshape(evecs[i*num_deg_freedom : 
                                                            (i+1)*num_deg_freedom, which],
                                                      (self.num_exc+1, self.num_exc+1)))
#                state_amplitudes = np.zeros_like(state_amplitudes)
#                state_amplitudes[2,0] = 1.0
                wavefunc_amplitudes += np.sum([state_amplitudes[s1, s2] * norm
                * np.multiply(self.harm_osc_wavefunction(s1, np.add.outer(Xi_inv[0,0]*phi_vec+phi1_s1_arg, 
                                                                          Xi_inv[0,1]*phi_vec+phi2_s1_arg)), 
                              self.harm_osc_wavefunction(s2, np.add.outer(Xi_inv[1,0]*phi_vec+phi1_s2_arg,
                                                                          Xi_inv[1,1]*phi_vec+phi2_s2_arg)))
                                               for s2 in range(self.num_exc+1) 
                                               for s1 in range(self.num_exc+1)], axis=0).T #FIX .T NOT CORRECT
                jkvals = next(klist,-1)
        
        grid2d = GridSpec(np.asarray([[phi_grid.min_val, phi_grid.max_val, phi_grid.pt_count],
                                      [phi_grid.min_val, phi_grid.max_val, phi_grid.pt_count]]))
    
        wavefunc_amplitudes = standardize_phases(wavefunc_amplitudes)

        return WaveFunctionOnGrid(grid2d, wavefunc_amplitudes)
    
   
    def plot_wavefunction(self, esys=None, which=0, phi_grid=None, mode='abs', zero_calibrate=True, **kwargs):
        """Plots 2d phase-basis wave function.

        Parameters
        ----------
        esys: ndarray, ndarray
            eigenvalues, eigenvectors as obtained from `.eigensystem()`
        which: int, optional
            index of wave function to be plotted (default value = (0)
        phi_grid: Grid1d, optional
            used for setting a custom grid for phi; if None use self._default_grid
        mode: str, optional
            choices as specified in `constants.MODE_FUNC_DICT` (default value = 'abs_sqr')
        zero_calibrate: bool, optional
            if True, colors are adjusted to use zero wavefunction amplitude as the neutral color in the palette
        **kwargs:
            plot options

        Returns
        -------
        Figure, Axes
        """
        amplitude_modifier = constants.MODE_FUNC_DICT[mode]
        wavefunc = self.wavefunction(esys, phi_grid=phi_grid, which=which)
        wavefunc.amplitudes = amplitude_modifier(wavefunc.amplitudes)
        if 'figsize' not in kwargs:
            kwargs['figsize'] = (5, 5)
        return plot.wavefunction2d(wavefunc, zero_calibrate=zero_calibrate, **kwargs)
    
    def _evals_calc(self, evals_count):
        hamiltonian_mat = self.hamiltonian()
        inner_product_mat = self.inner_product()
        try:
            evals = sp.linalg.eigh(hamiltonian_mat, b=inner_product_mat, 
                                   eigvals_only=True, eigvals=(0, evals_count - 1))
        except LinAlgError:
            print("exception")
#            global_min = self.sorted_minima()[0]
#            global_min_value = self.potential(global_min)
#            hamiltonian_mat += -global_min_value*inner_product_mat
            evals = sp.sparse.linalg.eigsh(hamiltonian_mat, k=evals_count, M=inner_product_mat, 
                                           sigma=0.00001, return_eigenvectors=False)
        return np.sort(evals)

    def _esys_calc(self, evals_count):
        hamiltonian_mat = self.hamiltonian()
        inner_product_mat = self.inner_product()
        try:
            evals, evecs = sp.linalg.eigh(hamiltonian_mat, b=inner_product_mat,
                                          eigvals_only=False, eigvals=(0, evals_count - 1))
            evals, evecs = order_eigensystem(evals, evecs)
        except LinAlgError:
            print("exception")
#            global_min = self.sorted_minima()[0]
#            global_min_value = self.potential(global_min)
#            hamiltonian_mat += -global_min_value*inner_product_mat
            evals, evecs = sp.sparse.linalg.eigsh(hamiltonian_mat, k=evals_count, M=inner_product_mat, 
                                                  sigma=0.00001, return_eigenvectors=True)
            evals, evecs = order_eigensystem(evals, evecs)
        return evals, evecs
    
    def plot_potential(self, phi_grid=None, contour_vals=None, **kwargs):
        """
        Draw contour plot of the potential energy.

        Parameters
        ----------
        phi_grid: Grid1d, optional
            used for setting a custom grid for phi; if None use self._default_grid
        contour_vals: list of float, optional
            specific contours to draw
        **kwargs:
            plot options
        """
        phi_grid = self._try_defaults(phi_grid)
        x_vals = y_vals = phi_grid.make_linspace()
        if 'figsize' not in kwargs:
            kwargs['figsize'] = (5, 5)
        return plot.contours(x_vals, y_vals, self.potential, contour_vals=contour_vals, **kwargs)
    
    def _full_o(self, operators, indices):
        i_o = np.eye(self.num_exc + 1)
        i_o_list = [i_o for k in range(2)]
        product_list = i_o_list[:]
        oi_list = zip(operators, indices)
        for oi in oi_list:
            product_list[oi[1]] = oi[0]
        full_op = self._kron_matrix_list(product_list)
        return(full_op)
    
    def _kron_matrix_list(self, matrix_list):
        output = matrix_list[0]
        for matrix in matrix_list[1:]:
            output = np.kron(output, matrix)
        return(output)
    
    def harm_osc_wavefunction(self, n, x):
        """For given quantum number n=0,1,2,... return the value of the harmonic oscillator wave function
        :math:`\\psi_n(x) = N H_n(x) \\exp(-x^2/2)`, N being the proper normalization factor. It is assumed
        that the harmonic length has already been accounted for. Therefore that portion of the normalization
        factor must be accounted for outside the function.

        Parameters
        ----------
        n: int
            index of wave function, n=0 is ground state
        x: float or ndarray
            coordinate(s) where wave function is evaluated

        Returns
        -------
        float or ndarray
            value(s) of harmonic oscillator wave function
        """
        return ((2.0 ** n * sp.special.gamma(n + 1.0)) ** (-0.5) * np.pi ** (-0.25) 
                * sp.special.eval_hermite(n, x) 
                * np.exp(-x**2/2.))
 