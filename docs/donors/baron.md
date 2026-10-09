# Baron: The Real Estate Simulation — property archaeology

## Evidence examined

- [World of Spectrum original Baron release record](https://worldofspectrum.net/item/0000423/),
  used to distinguish the 1983 management title from unrelated software with
  the same name.
- [ClassicReload description of Baron: The Real Estate Simulation](https://classicreload.com/baron-the-real-estate-simulation.html),
  which documents monthly real-estate activity, property trading, loans and
  changing investor status.
- [Computer Gaming World Issue 4.3 review](https://www.cgwmuseum.org/galleries/issues/cgw_4.3.pdf),
  which describes residential, business and undeveloped properties, market
  phases, graphs, prices and property-specific random events.

The original executable is archived, but an original source listing was not
located. The mechanics below are therefore behavioral extraction from the
release record and contemporary review, not numerical emulation.

## Mechanics verified

- Real property is held as an asset with a type, price and ownership.
- The game advances property-market activity in monthly periods and exposes
  changing market values.
- Properties can be bought and sold, rented, financed and affected by
  property-specific consequences.
- Wealth and investor status depend on the resulting asset and cash position.

## Selected for Redos

This checkpoint adds a small physical property layer to the canonical world:

- `Property` is anchored to an existing `Place` and has one canonical owner.
- Market updates change value through an explicit factor and preserve history.
- Purchases transfer money through `World.pay` before ownership changes.
- Leases and rent use the same money/event gateway as wages and contracts.

## Deliberately rejected

- A second clock or separate property-market inventory.
- Options, investor-class progression, graphs and presentation UI.
- Unverified formulas for interest rates, closing costs and random property
  incidents.
- Oil Barons' drilling and land-grid mechanics; that is a different title.

## Canonical state translation

| Donor phenomenon | Canonical state read | Canonical state changed |
| --- | --- | --- |
| Property holding | `Place`, `Property.owner_id` | Ownership and transfer event |
| Market phase | Explicit factor and world time | Value history and causal update |
| Purchase | Buyer/seller money | Payment and property transfer |
| Tenancy | Property occupancy and rent | Rent payment and ownership income |

## Tests

`tests/test_baron.py` verifies physical-place registration, value history,
ownership transfer, lease rent and failure-safe money behavior.

## Remaining uncertainty

The selected donor's exact name and platform variants are clear enough to
identify the real-estate lane, but the archived source and precise formulas
were not recovered. Redos preserves the causal property/equity mechanism and
leaves numerical details explicit for later evidence.
