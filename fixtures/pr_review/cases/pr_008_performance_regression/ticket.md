# PR-008: Add product recommendations to order confirmation

## Description
Enhance the order confirmation endpoint to include personalized product recommendations based on the items in the customer's order. This will help drive repeat purchases by showing related products.

## Requirements
- Include 5 recommended products in order confirmation response
- Recommendations based on items in the current order
- Exclude products already in the order
- Prioritize products from same category
- Fall back to bestsellers if no matches

## Acceptance Criteria
- [ ] Order confirmation includes recommendations array
- [ ] Recommendations are related to ordered items
- [ ] Already-purchased items are excluded
- [ ] Response time remains under 500ms
- [ ] Recommendations update based on order contents
- [ ] Endpoint handles edge cases (empty orders, new categories)