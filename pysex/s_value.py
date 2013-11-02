#!/usr/bin/env python

import z3
import s_helpers
import logging
import random
l = logging.getLogger("s_value")

class ConcretizingException(Exception):
        pass

workaround_counter = 0

class Value:
        def __init__(self, expr, constraints = None, lo = 0, hi = 2**64):
                self.expr = expr
                self.constraints = [ ]
                self.constraint_indexes = [ ]

                self.max_for_size = (2 ** self.expr.size() - 1) if z3.is_expr(expr) else 2**64
                self.min_for_size = 0

                self.solver = z3.Solver()
                if constraints != None:
                        self.push_constraints(constraints)


        @s_helpers.ondemand
        def any(self):
                return self.exactly_n(1)[0]

        @s_helpers.ondemand
        def is_unique(self):
                return len(self.any_n(2)) == 1

        @s_helpers.ondemand
        def satisfiable(self):
                try:
                        self.any()
                        return True
                except ConcretizingException:
                        return False

        def push_constraints(self, new_constraints):
                self.solver.push()
                self.constraint_indexes += [ len(self.constraints) ]
                self.constraints += new_constraints
                self.solver.add(*new_constraints)

        def pop_constraints(self):
                self.solver.pop()
                self.constraints = self.constraints[0:self.constraint_indexes.pop()]

        def exactly_n(self, n = 1, lo = 0, hi = 2**64):
                results = self.any_n(n, lo, hi)
                if len(results) != n:
                        #print "=-========================================="
                        #print self.expr
                        #print "-------------------------------------------"
                        #import pprint
                        #pprint.pprint(self._constraints)
                        #print "=========================================-="
                        raise ConcretizingException("Could only concretize %d/%d values." % (len(results), n))
                return results

        def any_n(self, n = 1, lo = 0, hi = 2**64):
        	global workaround_counter

                lo = max(lo, self.min_for_size)
                hi = min(hi, self.max_for_size)

                # handle constant variables
                if hasattr(self.expr, "as_long"):
                        return [ self.expr.as_long() ]

                self.solver.push()
                self.solver.add(z3.ULE(self.expr, hi))
                self.solver.add(z3.UGE(self.expr, lo))

                results = [ ]
                for i in range(n):
                        if results:
                                self.solver.add(self.expr != results[-1])

                        if self.solver.check() == z3.sat:
                                try:
                                        v = self.solver.model().get_interp(self.expr)
                                except z3.Z3Exception:
                                        # this happens (sometimes?) when we try to get the value of a BitVecRef.
                                        # Here's a (slower workaround)
                                        l.warning("Z3 refused to give the value of a BitVecRef. This is a slow workaround that should be replaced if this message shows up too frequently.")
                                        workaround_vec = z3.BitVec("workaround_%d" % workaround_counter, self.expr.size())
                                        workaround_counter += 1
                                        self.solver.add(self.expr == workaround_vec)
                                        self.solver.check() # this shouldn't affect SAT-ness, because we're just adding an alias for the expression
                                        v = self.solver.model().get_interp(workaround_vec)

                                if v is None:
                                        break

                                results.append(v.as_long())
                        else:
                                break

                self.solver.pop()
                return results

        @s_helpers.ondemand
        def min(self, lo = 0, hi = 2**64):
                lo = max(lo, self.min_for_size)
                hi = min(hi, self.max_for_size)

                ret = -1
                old_bnd = -1
                while 1:
                        bnd = lo + ((hi - lo) >> 1)
                        if bnd == old_bnd:
                                break

                        self.solver.push()
                        self.solver.add(z3.ULE(self.expr, bnd))
                        self.solver.add(z3.UGE(self.expr, lo))

                        if self.solver.check() == z3.sat:
                                hi = bnd
                                ret = bnd
                        else:
                                lo = bnd + 1

                        self.solver.pop()
                        old_bnd = bnd

                if ret == -1:
                        raise ConcretizingException("Unable to concretize expression %s" % str(self.expr))
                return ret

        @s_helpers.ondemand
        def max(self, lo = 0, hi = 2**64):
                lo = max(lo, self.min_for_size)
                hi = min(hi, self.max_for_size)

                ret = -1

                old_bnd = -1
                while 1:
                        bnd = lo + ((hi - lo) >> 1)
                        if bnd == old_bnd:
                                break

                        self.solver.push()
                        self.solver.add(z3.UGE(self.expr, bnd))
                        self.solver.add(z3.ULE(self.expr, hi))

                        if self.solver.check() == z3.sat:
                                lo = bnd
                                ret = bnd
                        else:
                                hi = bnd - 1

                        self.solver.pop()
                        old_bnd = bnd

                # The algorithm above retrieves the floor of the upper
                # bound range (i.e. [Floor_upper, Ceil_upper]. So we
                # have to try also the ceiling.
                if ret != -1:
                        self.solver.push()
                        self.solver.add(self.expr == (ret + 1))
                        self.solver.add(z3.ULE(self.expr, hi))
                        if self.solver.check() == z3.sat:
                                ret += 1
                        self.solver.pop()

                if ret == -1:
                        raise ConcretizingException("Unable to concretize expression %s", str(self.expr))
                return ret

        def rnd(self, lo=0, hi=2**64):
                lo = max(lo, self.min_for_size, self.min())
                hi = min(hi, self.max_for_size, self.max())

                n_rnd = random.randint(lo, hi)
                return self.min(lo=n_rnd)

        # iterates over all possible values
        def iter(self, lo=0, hi=2**64):
                lo = max(lo, self.min_for_size, self.min())
                hi = min(hi, self.max_for_size, self.max())

                self.current = lo
                while self.current <= hi:
                        self.current = self.min(self.current, hi)
                        yield self.current
                        self.current += 1

        def is_solution(self, solution):
                self.solver.push()
                self.solver.add(self.expr == solution)
                s = self.solver.check()
                self.solver.pop()
                return s == z3.sat

        # def _get_step(self, expr, start, stop, incr):
        #        lo = 0 if (start < 0) else start
        #        hi = ((1 << self.arch_bits) - 1) if (stop < 0) else stop
        #        incr = 1 if (incr <= 0) else incr
        #        s = Solver()

        #        gcd = -1
        #        unsat_steps = 0

        #        while lo <= hi:
        #                s.add(expr == lo)
        #                if  s.check() == sat:
        #                        gcd = unsat_steps if (gcd == -1) else fractions.gcd(gcd, unsat_steps)
        #                        if gcd == 1:
        #                                break
        #                        unsat_steps = 1
        #                else:
        #                        unsat_steps += 1
        #                        s.reset()
        #                lo = lo + incr

        #        return gcd
