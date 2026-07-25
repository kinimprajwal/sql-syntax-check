SELECT TOP 10 CustomerId, OrderDate
FROM dbo.Orders
WHERE WHERE OrderDate > '2026-01-01'
ORDER BY ORDER OrderDate DESC;
