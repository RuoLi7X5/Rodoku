import type { Technique } from './types'
import { nakedSingle } from './nakedSingle'
import { block } from './block'
import { pair } from './pair'
import { arrays } from './arrays'

/**
 * 技巧注册表：按顺序遍历执行。
 * 你后续新增 XYZ / UR 等技巧，只需：
 * 1) 在 src/techniques/ 下新增文件
 * 2) 在此处 import 并加入数组
 */
export const techniques: Technique[] = [
  nakedSingle,
  block,
  pair,
  arrays,
]


