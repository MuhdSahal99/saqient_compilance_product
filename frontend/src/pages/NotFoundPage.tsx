import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { EmptyState } from "@/components/common";
import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <EmptyState
      title={t("common.notFound")}
      description={t("common.notFoundHint")}
      action={
        <Button asChild variant="outline">
          <Link to="/">{t("nav.overview")}</Link>
        </Button>
      }
    />
  );
}
