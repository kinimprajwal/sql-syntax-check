CREATE OR ALTER PROCEDURE dbo.usp_GetActiveOrders_Broken
    @CustomerId INT,
    @StartDate  DATE = NULL
AS
BEGIN
    SET NOCOUNT ON

    SELECT
        o.OrderId,
        o.OrderDate,
        o.TotalAmount,
        c.CustomerName
    FROM dbo.Orders AS o
    INNER JOIN dbo.Customers AS c
        ON c.CustomerId = o.CustomerId
    WHERE WHERE o.CustomerId = @CustomerId
    ORDER BY ORDER o.OrderDate DESC;

    IF @@ROWCOUNT = 0
    BEGIN
        PRINT 'No active orders found for this customer.'
    -- missing END for the IF block, and missing final END for the procedure
GO
