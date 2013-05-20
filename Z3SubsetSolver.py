from z3 import *

def dimacs_var(i):
    if i not in dimacs_var.cache:
        if i > 0:
            dimacs_var.cache[i] = Bool(str(i))
        else:
            dimacs_var.cache[i] = Not(Bool(str(-i)))
    return dimacs_var.cache[i]
dimacs_var.cache = {}

def read_dimacs(filename):
    formula = []
    with open(filename) as f:
        for line in f:
            if line.startswith('c') or line.startswith('p'):
                continue
            clause = [int(x) for x in line.split()[:-1]]
            formula.append( Or( [dimacs_var(i) for i in clause] ) )
    return formula
            
def read_smt2(filename):
    formula = parse_smt2_file(filename)
    if is_and(formula):
        return formula.children()
    else:
        return [formula]

class Z3SubsetSolver:
    c_prefix = "!marco"  # to differentiate our vars from instance vars

    constraints = []
    n = 0
    s = None
    varcache = {}

    def __init__(self, filename):
        self.read_constraints(filename)
        self.make_solver()

    def read_constraints(self, filename):
        if filename.endswith('.cnf'):
            self.constraints = read_dimacs(filename)
        else:
            self.constraints = read_smt2(filename)
        self.n = len(self.constraints)

    def make_solver(self):
        self.s = Solver()
        for i in range(self.n):
            v = self.c_var(i)
            self.s.add(Implies(v, self.constraints[i]))

    def c_var(self, i):
        if i not in self.varcache:
            if i >= 0:
                self.varcache[i] = Bool(self.c_prefix+str(i))
            else:
                self.varcache[i] = Not(Bool(self.c_prefix+str(-i)))
        return self.varcache[i]

    def check_subset(self, seed):
        assumptions = self.to_c_lits(seed)
        return self.s.check(assumptions) == sat
        
    def to_c_lits(self, seed):
        return [self.c_var(i) for i in seed]

    def complement(self, aset):
        return set(range(self.n)) - aset

    def cname_to_int(self, name):
        return int(name[len(self.c_prefix):])

    def seed_from_core(self):
        core = self.s.unsat_core()
        return [self.cname_to_int(x.decl().name()) for x in core]

    def shrink_current(self):
        seed = self.seed_from_core()
        return self.shrink(seed)

    def shrink(self, seed):
        current = set(seed)
        for i in seed:
    #        if i not in current:
    #            # May have been "also-removed"
    #            continue
            if not self.check_subset(current - set([i])):
                # Remove any also-removed constraints
                #current = self.seed_from_core()  # doesn't seem to help much (I think the subset is almost always sat)
                current.remove(i)
        return current

    def grow_current(self):
        # TODO: not yet implemented...
        #       difficult to do efficiently...
        raise NotImplementedError
        #seed = seed_from_model(solver.model(), n)
        #return self.grow(seed)

    def grow(self, seed):
        current = set(seed)
        for i in self.complement(current):
    #        if i in current:
    #            # May have been "also-satisfied"
    #            continue
            if self.check_subset(current | set([i])):
                # Add any also-satisfied constraint
                #current = seed_from_model(s.model(), n)  # still too slow to help here
                current.add(i)
        return current

