-- Migration 013: Add child_safety to report_reason enum
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'report_reason'::regtype
          AND enumlabel = 'child_safety'
    ) THEN
        ALTER TYPE report_reason ADD VALUE 'child_safety';
    END IF;
END$$;
