# PR-002: Implement order discount calculator

## Description
Add a new `DiscountCalculator` service that handles various discount rules for orders, including percentage discounts, fixed amount discounts, and tiered discounts based on order value.

## Requirements
- Support percentage-based discounts (e.g., 10% off)
- Support fixed amount discounts (e.g., $20 off)
- Support tiered discounts based on order thresholds
- Handle multiple discount stacking rules
- Validate discount codes and expiration dates

## Acceptance Criteria
- [ ] Calculator correctly applies percentage discounts
- [ ] Calculator correctly applies fixed amount discounts
- [ ] Tiered discounts work for qualifying orders
- [ ] Stacking rules prevent invalid combinations
- [ ] Expired discount codes are rejected
- [ ] Invalid discount codes return appropriate errors