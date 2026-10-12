import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Compass, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4 py-12">
      <div className="flex max-w-md animate-fade-up flex-col items-center text-center">
        <div className="relative mb-6">
          <div className="absolute inset-0 -z-10 scale-150 rounded-full bg-teal-100/50 blur-2xl" aria-hidden />
          <div className="flex size-16 items-center justify-center rounded-2xl bg-white shadow-card ring-1 ring-slate-200/80">
            <Compass className="size-7 text-teal-600" aria-hidden />
          </div>
        </div>
        <p className="mb-2 font-mono text-xs font-semibold tracking-[0.2em] text-teal-700" aria-hidden>
          404
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-navy-950">{t("common.notFound")}</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">{t("common.notFoundHint")}</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button asChild variant="accent">
            <Link to="/">
              <ArrowLeft className="rtl-flip" aria-hidden />
              {t("nav.overview")}
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/documents">
              <FileText aria-hidden />
              {t("nav.documents")}
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
