import lancherLogo from './assets/lancher-code.png';

// 原图白色字形作为亮度蒙版；黑底不呈现，颜色跟随所在主题。
export function Brand({size=29,className=''}:{size?:number;className?:string}){
  const source=`url("${lancherLogo}")`;
  return <span className={'brand-symbol '+className} aria-hidden="true" style={{width:size,height:size,maskImage:source,WebkitMaskImage:source}}/>;
}
