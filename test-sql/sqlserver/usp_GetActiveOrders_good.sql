CREATE OR ALTER PROCEDURE dbo.usp_GetActiveOrders
    @CustomerId INT,
    @StartDate  DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    SELECT
        o.OrderId,
        o.OrderDate,
        o.TotalAmount,
        c.CustomerName
    FROM dbo.Orders AS o
    INNER JOIN dbo.Customers AS c
        ON c.CustomerId = o.CustomerId
    WHERE o.CustomerId = @CustomerId
        AND (@StartDate IS NULL OR o.OrderDate >= @StartDate)
    ORDER BY o.OrderDate DESC;

    IF @@ROWCOUNT = 0
    BEGIN
        PRINT 'No active orders found for this customer.';
    END
END
GO
