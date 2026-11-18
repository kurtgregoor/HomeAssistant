# Changelog

## 0.1.15

- Added an opt-in, read-only Energy Planner for two batteries. It reuses the tariff card and displays the 24-hour plan, simulated decisions, battery status and discharge blockers.
- Added import-quarter estimates, optional meter-reported quarter energy, and event-driven charge-budget checks.
- Added conservative per-battery energy accounting, evening-demand learning, prediction error history and explicit activation of the learned target in simulation after the shadow period.
- Added the versioned dashboard resource and planner configuration and status actions.
- Live actuation is gated pending V151 validation of safe Passive expiry and recovery. The existing battery actions and automations are available during simulation.
