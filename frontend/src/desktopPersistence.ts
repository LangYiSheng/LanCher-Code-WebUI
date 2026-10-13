// 单实例桌面状态串行落盘；失败项保留，下一次写入或退出时重试。
export class DesktopPersistence{
  private pending=new Map<string,string>();private tail=Promise.resolve();
  private save:(body:string)=>Promise<void>;
  constructor(save:(body:string)=>Promise<void>){this.save=save;}
  write(key:string,value:unknown){this.pending.set(key,JSON.stringify({key,value}));this.queue();}
  private queue(){this.tail=this.tail.catch(()=>{}).then(async()=>{for(const [key,body] of this.pending){await this.save(body);if(this.pending.get(key)===body)this.pending.delete(key);}});void this.tail.catch(()=>{});}
  async flush(){if(this.pending.size)this.queue();await this.tail;}
}
