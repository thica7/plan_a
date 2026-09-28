import { ListChecks } from "lucide-react";
import { useTranslation } from "../../stores/i18n";
import { SectionHeading } from "./SectionHeading";

interface ScopeSectionProps {
  setTopic: (topic: string) => void;
  topic: string;
  targetName: string;
  setTargetName: (value: string) => void;
  targetUrl: string;
  setTargetUrl: (value: string) => void;
  productCategory: string;
  setProductCategory: (value: string) => void;
  productAudience: string;
  setProductAudience: (value: string) => void;
  productUseCases: string;
  setProductUseCases: (value: string) => void;
  productMarket: string;
  setProductMarket: (value: string) => void;
}

export function ScopeSection({
  setTopic,
  topic,
  targetName, setTargetName, targetUrl, setTargetUrl,
  productCategory, setProductCategory, productAudience, setProductAudience,
  productUseCases, setProductUseCases, productMarket, setProductMarket,
}: ScopeSectionProps) {
  const { t } = useTranslation();
  return (
    <section className="form-section">
      <SectionHeading
        icon={<ListChecks size={17} aria-hidden />}
        index="01"
        meta={t('newRun.scopeDesc')}
        title={t('newRun.scope')}
      />
      <label className="field-block">
        {t('newRun.targetName')}
        <input required value={targetName} onChange={(event) => setTargetName(event.target.value)} />
      </label>
      <label className="field-block">{t('newRun.targetUrl')}
        <input type="url" placeholder="https://example.com/product" value={targetUrl} onChange={event => setTargetUrl(event.target.value)} />
      </label>
      <div className="scope-product-grid">
        <label className="field-block">{t('newRun.category')}
          <input value={productCategory} onChange={event => setProductCategory(event.target.value)} />
        </label>
        <label className="field-block">{t('newRun.audience')}
          <input value={productAudience} onChange={event => setProductAudience(event.target.value)} />
        </label>
        <label className="field-block">{t('newRun.useCases')}
          <input value={productUseCases} onChange={event => setProductUseCases(event.target.value)} placeholder={t('newRun.useCasesHint')} />
        </label>
        <label className="field-block">{t('newRun.market')}
          <input value={productMarket} onChange={event => setProductMarket(event.target.value)} />
        </label>
      </div>
      <label className="field-block">{t('newRun.topic')}
        <input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder={t('newRun.topicHint')} />
      </label>
    </section>
  );
}
