CREATE OR REPLACE PROCEDURE sp_refresh_customer_summary(customer_id NUMBER)
RETURNS STRING
LANGUAGE SQL
AS
$$
BEGIN
    MERGE INTO customer_summary AS tgt
    USING (
        SELECT
            customer_id,
            COUNT(*) AS order_count,
            SUM(total_amount) AS lifetime_value
        FROM orders
        WHERE customer_id = :customer_id
        GROUP BY customer_id
    ) AS src
    ON tgt.customer_id = src.customer_id
    WHEN MATCHED THEN UPDATE SET
        tgt.order_count = src.order_count,
        tgt.lifetime_value = src.lifetime_value
    WHEN NOT MATCHED THEN INSERT (customer_id, order_count, lifetime_value)
        VALUES (src.customer_id, src.order_count, src.lifetime_value);

    RETURN 'OK';
END;
$$;
