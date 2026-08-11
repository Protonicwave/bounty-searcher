"""Pure domain layer.

Nothing in this package performs I/O, reads the clock, or looks up
configuration. Every function takes what it needs as an argument and returns
new values rather than mutating its input. That is what makes scoring testable
without fixtures and re-scorable over the whole corpus in one local pass.
"""
