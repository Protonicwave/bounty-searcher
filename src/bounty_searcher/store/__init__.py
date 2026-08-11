"""The corpus.

A scan is not a query whose results are displayed. It is a crawler topping up a
local database that accumulates indefinitely, and everything above this layer
reads that database rather than the network.
"""
