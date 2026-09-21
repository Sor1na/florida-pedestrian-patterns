-- =====================================================================
-- 02_cardinality_triggers.sql
-- The "one or more" ends of two relationships in the ER diagram:
--     a crash kills ONE OR MORE pedestrians
--     a crash involves ONE OR MORE vehicles in transport
-- A foreign key can only say "every child has a parent". It cannot say
-- "every parent has a child", so these two rules need a trigger.
--
-- The triggers are DEFERRED: they run at COMMIT, not per statement.
-- That way a load can insert the crash first and its children next,
-- as long as they arrive in the same transaction.
-- =====================================================================

CREATE FUNCTION trg_crash_min_children() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    k_year smallint;
    k_case integer;
BEGIN
    IF TG_TABLE_NAME = 'crash' THEN          -- fired by INSERT on crash
        k_year := NEW.year;  k_case := NEW.st_case;
    ELSE                                     -- fired by DELETE/UPDATE on a child table
        k_year := OLD.year;  k_case := OLD.st_case;
    END IF;

    -- The crash itself is gone (ON DELETE CASCADE removed the children): nothing to protect.
    IF NOT EXISTS (SELECT 1 FROM crash c WHERE c.year = k_year AND c.st_case = k_case) THEN
        RETURN NULL;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pedestrian p WHERE p.year = k_year AND p.st_case = k_case) THEN
        RAISE EXCEPTION 'crash (%, %) has no pedestrian fatality row', k_year, k_case
            USING ERRCODE = 'check_violation', CONSTRAINT = 'crash_min_one_pedestrian', TABLE = 'crash';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM vehicle v WHERE v.year = k_year AND v.st_case = k_case) THEN
        RAISE EXCEPTION 'crash (%, %) has no in-transport vehicle row', k_year, k_case
            USING ERRCODE = 'check_violation', CONSTRAINT = 'crash_min_one_vehicle', TABLE = 'crash';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER crash_min_children_on_insert
    AFTER INSERT ON crash
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_crash_min_children();

CREATE CONSTRAINT TRIGGER crash_min_children_on_pedestrian_change
    AFTER DELETE OR UPDATE OF year, st_case ON pedestrian
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_crash_min_children();

CREATE CONSTRAINT TRIGGER crash_min_children_on_vehicle_change
    AFTER DELETE OR UPDATE OF year, st_case ON vehicle
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_crash_min_children();
