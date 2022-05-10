# This is to sidestep a numpy overhead introduced in numpy 1.17:
# https://stackoverflux.com/questions/61983372/is-built-in-method-numpy-core-multiarray-umath-implement-array-function-a-per
import os
os.environ['NUMPY_EXPERIMENTAL_ARRAY_FUNCTION'] = '0'
#----------------------------------
import numpy as np
import scipy.integrate
from scipy.integrate._ivp.base import OdeSolver

from ecoevocrm.type_set import *
from ecoevocrm.resource_set import *
import ecoevocrm.utils as utils


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

class ConsumerResourceSystem():

    # Define Class constants:
    CONSUMPTION_MODE_FASTEQ = 0
    CONSUMPTION_MODE_LINEAR = 1
    CONSUMPTION_MODE_MONOD  = 2
    INFLUX_MODE_NONE        = 0
    INFLUX_MODE_CONSTANT    = 1
    INFLUX_MODE_SINUSOID    = 2

    def __init__(self, 
                 type_set      = None,
                 resource_set  = None,
                 N_init        = None,
                 R_init        = None,
                 num_types     = None,
                 num_resources = None,
                 sigma         = None,
                 beta          = 1,
                 kappa         = 1e10,
                 eta           = 1,
                 lamda         = 0,
                 gamma         = 1,
                 xi            = 0,
                 chi           = None,
                 J             = None,
                 mu            = 1e-10,                 
                 rho           = 0,
                 tau           = 1,
                 omega         = 1,
                 D             = None,
                 resource_consumption_mode     = 'fast_resource_eq',
                 resource_influx_mode          = 'none',
                 threshold_min_abs_abundance   = 1,
                 threshold_min_rel_abundance   = 1e-6,
                 threshold_eq_abundance_change = 1e4,
                 threshold_precise_integrator  = 1e2,
                 check_event_low_abundance     = False,
                 seed = None):

        #----------------------------------

        if(seed is not None):
            np.random.seed(seed)
            self.seed = seed

        #----------------------------------
        # Determine the dimensions of the system:
        #----------------------------------
        if(type_set is not None):
            system_num_types     = type_set.num_types
            system_num_resources = type_set.num_traits
        elif(isinstance(sigma, (list, np.ndarray))):
           sigma = np.array(sigma)
           if(sigma.ndim == 2):
                system_num_types     = sigma.shape[0]
                system_num_resources = sigma.shape[1]
        else:
            if(num_types is not None):
                system_num_types = num_types
            elif(isinstance(N_init, (list, np.ndarray))):
                system_num_types = np.array(N_init).ravel().shape[0]
            else:
                utils.error("Error in ConsumerResourceSystem __init__(): Number of types must be specified by providing a) a type set, b) a sigma matrix, c) a num_types value, or d) a list for N_init.")
            #---
            if(resource_set is not None):
                system_num_resources = resource_set.num_resources
            elif(num_resources is not None):
                system_num_resources = num_resources
            elif(isinstance(R_init, (list, np.ndarray))):
                system_num_resources = np.array(R_init).ravel().shape[0]
            else:
                utils.error("Error in ConsumerResourceSystem __init__(): Number of resources must be specified by providing a) a resource set, b) a sigma matrix, c) a num_resources value, or d) a list for R_init.")
            
        #----------------------------------
        # Initialize type set parameters:
        #----------------------------------
        if(type_set is not None):
            if(isinstance(type_set, TypeSet)):
                self.type_set = type_set
            else:
                utils.error(f"Error in ConsumerResourceSystem __init__(): type_set argument expects object of TypeSet type.")
        else:
            self.type_set = TypeSet(num_types=system_num_types, num_traits=system_num_resources, sigma=sigma, beta=beta, kappa=kappa, eta=eta, lamda=lamda, gamma=gamma, xi=xi, chi=chi, J=J, mu=mu)
        # Check that the type set dimensions match the system dimensions:
        if(system_num_types != self.type_set.num_types): 
            utils.error(f"Error in ConsumerResourceSystem __init__(): Number of system types ({system_num_types}) does not match number of type set types ({self.type_set.num_types}).")
        if(system_num_resources != self.type_set.num_traits): 
            utils.error(f"Error in ConsumerResourceSystem __init__(): Number of system resources ({system_num_resources}) does not match number of type set traits ({self.type_set.num_traits}).")

        # Reference the TypeSet's lineage_ids property to induce assignment of a non-None lineage_id attribute 
        # (waiting to induce assignment of lineage ids until after a large sim can cause a RecursionError):
        self.type_set.lineage_ids
        
        #----------------------------------
        # Initialize resource set parameters:
        #----------------------------------
        if(resource_set is not None):
            if(isinstance(resource_set, ResourceSet)):
                self.resource_set = resource_set
            else:
                utils.error(f"Error in ConsumerResourceSystem __init__(): resource_set argument expects object of ResourceSet type.")
        else:
            self.resource_set = ResourceSet(num_resources=system_num_resources, rho=rho, tau=tau, omega=omega, D=D)
        # Check that the type set dimensions match the system dimensions:
        if(system_num_resources != self.resource_set.num_resources): 
            utils.error(f"Error in ConsumerResourceSystem __init__(): Number of system resources ({system_num_resources}) does not match number of resource set resources ({self.resource_set.num_resources}).")

        #----------------------------------
        # Initialize system variables:
        #----------------------------------
        if(N_init is None or R_init is None):
            utils.error(f"Error in ConsumerResourceSystem __init__(): Values for N_init and R_init must be provided.")
        self._N_series = utils.ExpandableArray(utils.reshape(N_init, shape=(system_num_types, 1)), alloc_shape=(max(self.resource_set.num_resources*25, system_num_types), 1))
        self._R_series = utils.ExpandableArray(utils.reshape(R_init, shape=(system_num_resources, 1)), alloc_shape=(self.resource_set.num_resources, 1))

        #----------------------------------
        # Initialize system time:
        #----------------------------------
        self._t_series = utils.ExpandableArray([0], alloc_shape=(1, 1))

        #----------------------------------
        # Initialize event parameters:
        #----------------------------------
        self.threshold_mutation_propensity = None # is updated in run()
        self.threshold_eq_abundance_change = threshold_eq_abundance_change
        self.threshold_min_abs_abundance   = threshold_min_abs_abundance
        self.threshold_min_rel_abundance   = threshold_min_rel_abundance
        self.threshold_precise_integrator  = threshold_precise_integrator
        self.check_event_low_abundance     = check_event_low_abundance

        #----------------------------------
        # Initialize system options:
        #----------------------------------
        self.resource_consumption_mode = ConsumerResourceSystem.CONSUMPTION_MODE_FASTEQ if resource_consumption_mode=='fast_resource_eq' \
                                          else ConsumerResourceSystem.CONSUMPTION_MODE_LINEAR if resource_consumption_mode=='linear' \
                                          else ConsumerResourceSystem.CONSUMPTION_MODE_MONOD if resource_consumption_mode=='monod' \
                                          else -1

        self.resource_influx_mode      = ConsumerResourceSystem.INFLUX_MODE_NONE if resource_influx_mode == 'none' \
                                          else ConsumerResourceSystem.INFLUX_MODE_CONSTANT if resource_influx_mode == 'constant' \
                                          else ConsumerResourceSystem.INFLUX_MODE_SINUSOID if resource_influx_mode == 'sinusoid' \
                                          else -1

        #----------------------------------
        # Initialize set of mutant types:
        #----------------------------------
        self.mutant_set = self.type_set.generate_mutant_set()


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    @staticmethod
    def get_array(arr):
        return arr.values if isinstance(arr, utils.ExpandableArray) else arr

    @property
    def N_series(self):
        return ConsumerResourceSystem.get_array(self._N_series)

    @property
    def N(self):
        return self.N_series[:, -1]

    @property
    def R_series(self):
        return ConsumerResourceSystem.get_array(self._R_series)

    @property
    def R(self):
        return self.R_series[:, -1]       

    @property
    def t_series(self):
        return ConsumerResourceSystem.get_array(self._t_series).ravel()

    @property
    def t(self):
        return self.t_series[-1]

    @property
    def extant_type_indices(self):
        return np.where(self.N > 0)[0]

    @property
    def extant_type_set(self):
        return self.get_extant_type_set()

    @property
    def abundance(self):
        return self.N

    @property
    def rel_abundance(self):
        return self.N/np.sum(self.N)

    @property
    def biomass(self):
        return np.sum(self.N)

    @property
    def fitness(self):
        return self.growth_rate(self.N, self.R, self.type_set.sigma, self.type_set.beta, self.type_set.kappa, self.type_set.eta, self.type_set.lamda, self.type_set.gamma, self.type_set.energy_costs, self.resource_set.omega, self.resource_consumption_mode)
    
    @property
    def num_types(self):
        return self.type_set.num_types

    @property
    def num_resources(self):
        return self.resource_set.num_resources

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def run(self, T, dt=None, integration_method='default', reorder_types_by_phylogeny=True):

        t_start   = self.t
        t_elapsed = 0

        self._t_series.expand_alloc((self._t_series.alloc[0], self._t_series.alloc[1]+int(T/dt if dt is not None else 10000)))
        self._N_series.expand_alloc((self._N_series.alloc[0], self._N_series.alloc[1]+int(T/dt if dt is not None else 10000)))
        self._R_series.expand_alloc((self._R_series.alloc[0], self._R_series.alloc[1]+int(T/dt if dt is not None else 10000)))

        while(t_elapsed < T):

            #------------------------------
            # Set initial conditions and integration variables:
            #------------------------------
           
            # Set the time interval for this integration epoch:
            t_span = (self.t, self.t+T)

            # Set the time ticks at which to save trajectory values:
            t_eval = np.arange(start=t_span[0], stop=t_span[1]+dt, step=dt) if dt is not None else None,

            # Get the indices and count of extant types (abundance > 0):
            self._active_type_indices = self.extant_type_indices
            num_extant_types = len(self._active_type_indices)

            # Set the initial conditions for this integration epoch:
            N_init = self.N[self._active_type_indices] 
            R_init = self.R 
            cumPropMut_init = np.array([0])
            init_cond = np.concatenate([N_init, R_init, cumPropMut_init])

            # Get the params for the dynamics:
            params = self.get_dynamics_params(self._active_type_indices)

            # Draw a random propensity threshold for triggering the next Gillespie mutation event:
            self.threshold_mutation_propensity = np.random.exponential(1)
            
            # Set the integration method:
            if(integration_method == 'default'):
                if(num_extant_types <= self.threshold_precise_integrator):
                    _integration_method = 'LSODA' # accurate stiff integrator
                else:
                    _integration_method = 'LSODA' # adaptive stiff/non-stiff integrator
            else:
                _integration_method = integration_method

            #------------------------------
            # Integrate the system dynamics:
            #------------------------------
            
            sol = scipy.integrate.solve_ivp(self.dynamics, 
                                             y0     = init_cond,
                                             args   = params,
                                             t_span = (self.t, self.t+T),
                                             t_eval = np.arange(start=self.t, stop=self.t+T+dt, step=dt) if dt is not None else None,
                                             events = [self.event_mutation, self.event_low_abundance] if self.check_event_low_abundance else [self.event_mutation],
                                             method = _integration_method )

            #------------------------------
            # Update the system's trajectories with latest dynamics epoch:
            #------------------------------

            N_epoch = np.zeros(shape=(self._N_series.shape[0], len(sol.t)))
            N_epoch[self._active_type_indices] = sol.y[:num_extant_types]
            
            R_epoch = sol.y[-1-self.resource_set.num_resources:-1]
            
            self._t_series.add(sol.t, axis=1)
            self._N_series.add(N_epoch, axis=1)
            self._R_series.add(R_epoch, axis=1)
            
            t_elapsed = self.t - t_start

            typeCountStr = f"{num_extant_types}/{self.type_set.num_types}*({self.mutant_set.num_types})"

            #------------------------------
            # Handle events and update the system's states accordingly:
            #------------------------------
            if(sol.status == 1): # An event occurred
                if(len(sol.t_events[0]) > 0):
                    print(f"[ Mutation event occurred at  t={self.t:.4f} {typeCountStr}]\t\r", end="")
                    self.handle_mutation_event()
                    self.handle_type_loss()
                if(len(sol.t_events) > 1 and len(sol.t_events[1]) > 0):
                    print(f"[ Low abundance event occurred at  t={self.t:.4f} {typeCountStr}]\t\r", end="")
                    # print(f"\n\n[ Low abundance event occurred at  t={self.t:.4f} {typeCountStr}]\n\n")
                    self.handle_type_loss()
            elif(sol.status == 0): # Reached end T successfully
                self.handle_type_loss()
            else: # Error occurred in integration
                utils.error("Error in ConsumerResourceSystem run(): Integration of dynamics using scipy.solve_ivp returned with error status.")

        #------------------------------
        # Finalize data series at end of integration period:
        #------------------------------

        self._t_series.trim()
        self._N_series.trim()
        self._R_series.trim()

        if(reorder_types_by_phylogeny):
            self.reorder_types()

        return


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def dynamics(self, t, variables, 
                    num_types, num_mutants, sigma, beta, kappa, eta, lamda, gamma, xi, chi, J, mu, energy_costs, energy_uptake_coeffs,
                    num_resources, rho, tau, omega, D, resource_consumption_mode, resource_influx_mode):

        N_t = np.zeros(num_types+num_mutants)
        N_t[:num_types] = variables[:num_types]

        R_t = variables[-1-num_resources:-1]

        #------------------------------

        resource_influx_rate  = rho + alpha*np.sin(theta * (t + phi)) if self.resource_influx_mode == ConsumerResourceSystem.INFLUX_MODE_SINUSOID else rho

        #------------------------------

        growth_rate = ConsumerResourceSystem.growth_rate(N_t, R_t, sigma, beta, kappa, eta, lamda, gamma, energy_costs, omega, resource_consumption_mode, energy_uptake_coeffs)
        
        dNdt = N_t[:num_types] * growth_rate[:num_types] # only calc dNdt for extant (non-mutant) types

        #------------------------------

        dRdt = np.zeros(num_resources)

        #------------------------------

        self.mutant_fitnesses = growth_rate[-num_mutants:]

        self.mutation_propensities = np.maximum(0, self.mutant_fitnesses * np.repeat(N_t[:num_types] * mu, repeats=num_resources))
                                                          
        dCumPropMut = np.sum(self.mutation_propensities, keepdims=True)
        
        #------------------------------

        return np.concatenate((dNdt, dRdt, dCumPropMut))


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    @staticmethod
    def growth_rate(N, R, sigma, beta, kappa, eta, lamda, gamma, energy_costs, omega, resource_consumption_mode, energy_uptake_coeffs=None):
        # TODO: Allow for calculating for single N/R or time series of N/Rs
        energy_uptake_coeffs = omega * (1-lamda) * sigma * beta if energy_uptake_coeffs is None else energy_uptake_coeffs
        #------------------------------
        if(resource_consumption_mode == ConsumerResourceSystem.CONSUMPTION_MODE_FASTEQ):
            
            # UPDATE ATTEMPT 1:
            # resource_demand = ConsumerResourceSystem.resource_demand(N, sigma)
            # resource_uptake = resource_influx_rate / (resource_decay_rate + np.einsum('ij,j->ij', consumption_rate_percapita, resource_demand) if consumption_rate_percapita.ndim == 2 else np.einsum('j,j->j', consumption_rate_percapita, resource_demand))
            # energy_uptake   = np.einsum(('ij,ij->i' if resource_uptake.ndim == 2 else 'ij,j->i'), consumption_rate_bytrait, resource_uptake)
            # energy_surplus  = energy_uptake - energy_costs
            # growth_rate     = gamma * energy_surplus
            
            # ORIGINAL:
            resource_demand = ConsumerResourceSystem.resource_demand(N, sigma)
            energy_uptake   = np.einsum(('ij,ij->i' if kappa.ndim == 2 else 'ij,j->i'), energy_uptake_coeffs, kappa/(kappa + resource_demand))
            energy_surplus  = energy_uptake - energy_costs
            growth_rate     = gamma * energy_surplus

        elif(resource_consumption_mode == ConsumerResourceSystem.CONSUMPTION_MODE_LINEAR):
            pass
        elif(resource_consumption_mode == ConsumerResourceSystem.CONSUMPTION_MODE_MONOD):
            pass
        else:
            pass
        #------------------------------
        return growth_rate


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    @staticmethod
    def resource_demand(N, sigma):
        return np.einsum(('ij,ij->j' if N.ndim == 2 else 'i,ij->j'), N, sigma)

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def event_mutation(self, t, variables, *args):
        cumulative_mutation_propensity = variables[-1]
        return self.threshold_mutation_propensity - cumulative_mutation_propensity
    #----------------------------------
    event_mutation.direction = -1
    event_mutation.terminal  = True


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def event_low_abundance(self, t, variables, *args):
        num_types = args[0]
        N_t = variables[:num_types]
        #------------------------------
        abundances_abs = N_t[N_t > 0]
        abundances_rel = abundances_abs/np.sum(abundances_abs)
        # print("# ", np.min( abundances_abs), 
        #                     np.any(abundances_abs < self.threshold_min_abs_abundance), 
        #                     np.min(abundances_rel),
        #                     np.any(abundances_rel < self.threshold_min_rel_abundance),
        #                     '-' if np.any(abundances_abs < self.threshold_min_abs_abundance) or np.any(abundances_rel < self.threshold_min_rel_abundance) else 1)
        return -1 if np.any(abundances_abs < self.threshold_min_abs_abundance) or np.any(abundances_rel < self.threshold_min_rel_abundance) else 1
    #------------------------------
    event_low_abundance.direction = -1
    event_low_abundance.terminal  = True

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def handle_mutation_event(self):
        # Pick the mutant that will be established with proababilities proportional to mutants' propensities for establishment:
        mutant_indices   = self.type_set.get_mutant_indices(self._active_type_indices)
        mutant_drawprobs = self.mutation_propensities/np.sum(self.mutation_propensities)
        mutant_idx       = np.random.choice(mutant_indices, p=mutant_drawprobs)
        # Retrieve the mutant and some of its properties:
        mutant           = self.mutant_set.get_type(mutant_idx)
        mutant_type_id   = self.mutant_set.get_type_id(mutant_idx)
        mutant_fitness   = self.mutant_fitnesses[np.argmax(mutant_indices == mutant_idx)]
        mutant_abundance = np.maximum(1/mutant_fitness, 1) # forcing abundance of new types to be at least 1, this is a Ryan addition (perhaps controversial)
        # Get the index of the parent of the selected mutant:
        parent_idx       = mutant_idx // self.type_set.num_traits
        # print(self.type_set.type_ids)
        # print(mutant_type_id)
        #----------------------------------
        if(mutant_type_id in self.type_set.type_ids):
            # print("pre-existing")
            # This "mutant" is a pre-existing type in the population; get its index:
            preexisting_type_idx = np.where(np.array(self.type_set.type_ids) == mutant_type_id)[0][0]
            # Add abundance equal to the mutant's establishment abundance to the pre-existing type:
            self.set_type_abundance(type_index=preexisting_type_idx, abundance=self.get_type_abundance(preexisting_type_idx)+mutant_abundance)
            # Remove corresonding abundance from the parent type (abundance is moved from parent to mutant):
            self.set_type_abundance(type_index=parent_idx, abundance=max(self.get_type_abundance(parent_idx)-mutant_abundance, 1))
        else:
            # print("new mutant type", mutant.sigma)
            # Add the mutant to the population at an establishment abundance equal to 1/dfitness:
            self.add_type(mutant, abundance=mutant_abundance, parent_index=parent_idx)
            # Remove corresonding abundance from the parent type (abundance is moved from parent to mutant):
            self.set_type_abundance(type_index=parent_idx, abundance=max(self.get_type_abundance(parent_idx)-mutant_abundance, 1))
        #----------------------------------
        return
    

    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def handle_type_loss(self):
        N = self.N
        R = self.R
        #----------------------------------
        growth_rate = ConsumerResourceSystem.growth_rate(N, R, self.type_set.sigma, self.type_set.beta, self.type_set.kappa, self.type_set.eta, self.type_set.lamda, self.type_set.gamma, self.type_set.energy_costs, self.resource_set.omega, self.resource_consumption_mode) 
        #----------------------------------
        lost_types = np.where( (N < 0) | ((N > 0) & (growth_rate < 0) & ((N < self.threshold_min_abs_abundance) | (N/np.sum(N) < self.threshold_min_rel_abundance))) )[0]
        for i in lost_types:
            self.set_type_abundance(type_index=i, abundance=0.0) # Set the abundance of lost types to 0 (but do not remove from system/type set data)
        #----------------------------------
        return

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def add_type(self, new_type_set=None, abundance=0, parent_index=None, parent_id=None):#, index=None, ):
        abundance      = utils.treat_as_list(abundance)
        #----------------------------------
        self.type_set.add_type(new_type_set, parent_index=parent_index, parent_id=parent_id)
        #----------------------------------
        self._N_series = self._N_series.add(np.zeros(shape=(new_type_set.num_types, self.N_series.shape[1])))
        self.set_type_abundance(type_index=list(range(self.type_set.num_types-new_type_set.num_types, self.type_set.num_types)), abundance=abundance)
        #----------------------------------
        self.mutant_set.add_type(new_type_set.generate_mutant_set())

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def set_type_abundance(self, abundance, type_index=None, type_id=None, t=None, t_index=None):
        abundance    = utils.treat_as_list(abundance)
        type_indices = [ np.where(self.type_set.type_ids==tid)[0] for tid in utils.treat_as_list(type_id) ] if type_id is not None else utils.treat_as_list(type_index)
        t_idx        = np.argmax(self.t_series >= t) if t is not None else t_index if t_index is not None else -1
        #----------------------------------
        for i, type_idx in enumerate(type_indices):
            self.N_series[type_idx, t_idx] = abundance[i]

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_type_abundance(self, type_index=None, type_id=None, t=None, t_index=None):
        type_indices = [ np.where(np.array(self.type_set.type_ids) == tid)[0] for tid in utils.treat_as_list(type_id) ] if type_id is not None else utils.treat_as_list(type_index) if type_index is not None else list(range(self.type_set.num_types))
        time_indices = [ np.where(self.t_series == t_)[0] for t_ in utils.treat_as_list(t) ] if t is not None else utils.treat_as_list(t_index) if t_index is not None else -1
        #----------------------------------
        abundances = self.N_series[type_indices, time_indices]
        return abundances if len(type_indices) > 1 else abundances[0]

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_dynamics_params(self, type_indices=None):
        type_params     = self.type_set.get_dynamics_params(type_indices)
        mutant_params   = self.mutant_set.get_dynamics_params(self.type_set.get_mutant_indices(type_indices))
        resource_params = self.resource_set.get_dynamics_params()
        #----------------------------------
        type_params_wmuts = {
                              'num_types':    type_params['num_types'], 
                              'num_mutants':  mutant_params['num_types'],
                              'sigma':        np.concatenate([type_params['sigma'], mutant_params['sigma']]),
                              'beta':         type_params['beta'] if type_params['beta'].ndim < 2 else np.concatenate([type_params['beta'], mutant_params['beta']]),
                              'kappa':        type_params['kappa'] if type_params['kappa'].ndim < 2 else np.concatenate([type_params['kappa'], mutant_params['kappa']]),
                              'eta':          type_params['eta'] if type_params['eta'].ndim < 2 else np.concatenate([type_params['eta'], mutant_params['eta']]),
                              'lamda':        type_params['lamda'] if type_params['lamda'].ndim < 2 else np.concatenate([type_params['lamda'], mutant_params['lamda']]),
                              'gamma':        type_params['gamma'] if type_params['gamma'].ndim < 2 else np.concatenate([type_params['gamma'], mutant_params['gamma']]),
                              'xi':           type_params['xi'] if type_params['xi'].ndim < 2 else np.concatenate([type_params['xi'], mutant_params['xi']]),
                              'chi':          type_params['chi'] if type_params['chi'].ndim < 2 else np.concatenate([type_params['chi'], mutant_params['chi']]),
                              'J':            type_params['J'],
                              'mu':           type_params['mu'] if type_params['mu'].ndim < 2 else np.concatenate([type_params['mu'], mutant_params['mu']]),
                              'energy_costs': np.concatenate([type_params['energy_costs'], mutant_params['energy_costs']]) 
                            }
        #----------------------------------
        energy_uptake_coeffs = resource_params['omega'] * (1-type_params_wmuts['lamda']) * type_params_wmuts['sigma'] * type_params_wmuts['beta']
        #----------------------------------
        return (tuple(type_params_wmuts.values()) + (energy_uptake_coeffs,)
                + tuple(resource_params.values())
                + (self.resource_consumption_mode, self.resource_influx_mode))

    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def reorder_types(self, order=None):
        type_order   = np.argsort(self.type_set.lineage_ids) if order is None else order
        mutant_order = self.type_set.get_mutant_indices(type_order)
        #----------------------------------
        self._N_series = self._N_series.reorder(type_order)
        self.type_set.reorder_types(type_order) # don't need to reorder mutant_set because type_set.mutant_indices gets reordered and keeps correct pointers


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_extant_type_set(self, type_set=None, t=None, t_index=None):
        t_idx = np.argmax(self.t_series >= t) if t is not None else t_index if t_index is not None else -1
        type_set = self.type_set if type_set is None else type_set
        #----------------------------------
        if(t_idx == -1):
            return type_set.get_type(self.extant_type_indices)
        else:
            _extant_type_indices = np.where(self.N_series[:, t_idx] > 0)[0]
            return type_set.get_type(_extant_type_indices)


    def get_extant_type_indices(self, t=None, t_index=None):
        t_idx = np.argmax(self.t_series >= t) if t is not None else t_index if t_index is not None else -1
        #----------------------------------
        return np.where(self.N_series[:, t_idx] > 0)[0]


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def combine(self, added_system):

        # This implementation assumes that the 'self' system that is combined 'into' keeps its thresholds and other metadata attributes.
        # TODO: Properly combine resource sets (right now the 'self' system resources are kept as is)
        #----------------------------------
        # TODO: At the moment, it seems that there is no good way to reconcile parent indices and phylogenies/lineage ids from multiple systems,
        # so these are currently being reset in the combined system.
        self.type_set._parent_indices = [None for i in range(self.num_types)]
        self.type_set._lineage_ids    = None
        #----------------------------------
        for comb_type_idx in range(added_system.type_set.num_types):
            # Retrieve the added type and some of its properties:
            comb_type    = added_system.type_set.get_type(comb_type_idx)
            comb_type_id = added_system.type_set.get_type_id(comb_type_idx)
            comb_type_abundance = added_system.N[comb_type_idx]
            #----------------------------------
            if(comb_type_id in self.type_set.type_ids):
                # The added type is a pre-existing type in the current population; get its index:
                preexisting_type_idx = np.where(np.array(self.type_set.type_ids) == comb_type_id)[0][0]
                # Add abundance equal to the added types abundance:
                self.set_type_abundance(type_index=preexisting_type_idx, abundance=self.get_type_abundance(preexisting_type_idx)+comb_type_abundance)
            else:
                # The added type is not present in the current population:
                # Add the new type to the population at its abundance in the added_system:
                self.add_type(comb_type, abundance=comb_type_abundance, parent_index=None) # note that parent_index is None here under assumption that parent indices need to be reset in combined systems
            #----------------------------------
        return self


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def perturb(self, param, dist, args, mode='multiplicative_proportional', element_wise=True):
        params = utils.treat_as_list(param)
        #----------------------------------
        for param in params:
            if(param == 'beta'): 
                perturb_vals    = utils.get_perturbations(self.type_set.beta, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.beta = (self.type_set.beta * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.beta * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.beta + perturb_vals) if mode == 'additive' else self.type_set.beta
            elif(param == 'kappa'): 
                perturb_vals    = utils.get_perturbations(self.type_set.kappa, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.kappa = (self.type_set.kappa * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.kappa * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.kappa + perturb_vals) if mode == 'additive' else self.type_set.kappa
            elif(param == 'eta'): 
                perturb_vals    = utils.get_perturbations(self.type_set.eta, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.eta = (self.type_set.eta * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.eta * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.eta + perturb_vals) if mode == 'additive' else self.type_set.eta
            elif(param == 'lamda'): 
                perturb_vals    = utils.get_perturbations(self.type_set.lamda, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.lamda = (self.type_set.lamda * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.lamda * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.lamda + perturb_vals) if mode == 'additive' else self.type_set.lamda
            elif(param == 'gamma'): 
                perturb_vals    = utils.get_perturbations(self.type_set.gamma, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.gamma = (self.type_set.gamma * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.gamma * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.gamma + perturb_vals) if mode == 'additive' else self.type_set.gamma
            elif(param == 'xi'): 
                perturb_vals    = utils.get_perturbations(self.type_set.xi, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.xi = (self.type_set.xi * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.xi * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.xi + perturb_vals) if mode == 'additive' else self.type_set.xi
            elif(param == 'chi'): 
                perturb_vals    = utils.get_perturbations(self.type_set.chi, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.chi = (self.type_set.chi * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.chi * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.chi + perturb_vals) if mode == 'additive' else self.type_set.chi
            elif(param == 'mu'): 
                perturb_vals    = utils.get_perturbations(self.type_set.mu, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.type_set.mu = (self.type_set.mu * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.type_set.mu * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.type_set.mu + perturb_vals) if mode == 'additive' else self.type_set.mu
            elif(param == 'rho'): 
                perturb_vals    = utils.get_perturbations(self.resource_set.rho, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.resource_set.rho = (self.resource_set.rho * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.resource_set.rho * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.resource_set.rho + perturb_vals) if mode == 'additive' else self.resource_set.rho
            elif(param == 'tau'): 
                perturb_vals    = utils.get_perturbations(self.resource_set.tau, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.resource_set.tau = (self.resource_set.tau * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.resource_set.tau * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.resource_set.tau + perturb_vals) if mode == 'additive' else self.resource_set.tau
            elif(param == 'omega'): 
                perturb_vals    = utils.get_perturbations(self.resource_set.omega, dist=dist, args=args, mode=mode, element_wise=element_wise)
                self.resource_set.omega = (self.resource_set.omega * (1 + np.maximum(perturb_vals, -1))) if mode == 'multiplicative_proportional' else (self.resource_set.omega * np.maximum(perturb_vals, 0)) if mode == 'multiplicative' else (self.resource_set.omega + perturb_vals) if mode == 'additive' else self.resource_set.omega
        #----------------------------------
        return self


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_fitness(self, t=None, t_index=None):
        t_idx        = np.argmax(self.t_series >= t) if t is not None else t_index if t_index is not None else -1
        return self.growth_rate(self.N_series[:, t_idx], self.R_series[:, t_idx], self.type_set.sigma, self.type_set.beta, self.type_set.kappa, self.type_set.eta, self.type_set.lamda, self.type_set.gamma, self.type_set.energy_costs, self.resource_set.omega, self.resource_consumption_mode)


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_most_fit_types(self, rank_cutoff=None, fitness_cutoff=None, t=None, t_index=None):
        rank_cutoff    = 1 if rank_cutoff is None else rank_cutoff
        fitness_cutoff = np.min(self.fitness) if fitness_cutoff is None else fitness_cutoff
        t_idx          = np.argmax(self.t_series >= t) if t is not None else t_index if t_index is not None else -1
        #----------------------------------
        return self.type_set.get_type(self.get_fitness(t_index=t_idx)[self.get_fitness(t_index=t_idx) >= fitness_cutoff].argsort()[::-1][:rank_cutoff])


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_lowest_cost_types(self, rank_cutoff=None, cost_cutoff=None):
        rank_cutoff = 1 if rank_cutoff is None else rank_cutoff
        cost_cutoff = np.max(self.type_set.energy_costs) if cost_cutoff is None else cost_cutoff
        #----------------------------------
        return self.type_set.get_type(self.type_set.energy_costs[self.type_set.energy_costs <= cost_cutoff].argsort()[:rank_cutoff])

            
            











    