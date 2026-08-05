"""Adaptive Red: evolves structured synthetic strategy data only.

Nothing in this package writes Python, safety policy, registries, renderer
code, templates, workflows, or the action space itself. A strategy is a frozen
mapping of allowlisted field names to allowlisted enum values, and every
candidate is validated before it is ever executed.
"""
