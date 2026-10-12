import { useTranslation } from "react-i18next";
import { FileCheck2, FileText, Sheet } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Report } from "@/lib/types";

export function ReportLinks({ report }: { report: Report }) {
  const { t } = useTranslation();
  const base = `/api/reports/${report.id}/export?format=`;
  return (
    <div className="flex flex-wrap gap-2">
      <Button asChild size="sm" variant="outline">
        <a href={`${base}html`} target="_blank" rel="noopener noreferrer">
          <FileText aria-hidden /> {t("reports.html")}
        </a>
      </Button>
      <Button asChild size="sm" variant="outline">
        <a href={`${base}pdf`}>
          <FileCheck2 aria-hidden /> {t("reports.pdf")}
        </a>
      </Button>
      <Button asChild size="sm" variant="outline">
        <a href={`${base}csv`}>
          <Sheet aria-hidden /> {t("reports.csv")}
        </a>
      </Button>
    </div>
  );
}

