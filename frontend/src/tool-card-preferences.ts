export type ToolSection = 'card' | 'parameters' | 'result' | 'artifact' | 'raw';
interface Disclosure {
  card:boolean; parameters:boolean; result:boolean; artifact:boolean; raw:boolean;
  seenFailure:boolean; touchedCard:boolean; touchedResult:boolean;
}
const defaults = (failed:boolean): Disclosure => ({
  card:failed, parameters:false, result:failed, artifact:false, raw:false,
  seenFailure:failed, touchedCard:false, touchedResult:false,
});

/** 应用内阅读偏好，与事实、审批和 localStorage 无关。 */
export class ToolCardPreferences {
  private choices = new Map<string, Disclosure>();
  private listeners = new Set<() => void>();
  private version = 0;
  getSnapshot = () => this.version;
  subscribe = (listener:() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  read(identity:string, failed:boolean) { return this.choices.get(identity) ?? defaults(failed); }
  private save(identity:string, choice:Disclosure) {
    this.choices.set(identity, choice);
    this.version++;
    this.listeners.forEach(listener => listener());
  }
  observeFailure(identity:string, failed:boolean) {
    if (!failed) return;
    const previous = this.choices.get(identity);
    if (previous?.seenFailure) return;
    const choice = previous ?? defaults(false);
    this.save(identity, {...choice, seenFailure:true,
      card:choice.touchedCard ? choice.card : true, result:choice.touchedResult ? choice.result : true});
  }
  toggle(identity:string, section:ToolSection, failed:boolean) {
    const previous = this.read(identity, failed);
    this.save(identity, {...previous, [section]:!previous[section],
      touchedCard:previous.touchedCard || section === 'card',
      touchedResult:previous.touchedResult || section === 'result'});
  }
}
