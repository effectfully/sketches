{-# OPTIONS_GHC -O2 #-}
{-# OPTIONS_GHC -fno-warn-incomplete-uni-patterns #-}
{-# OPTIONS_GHC -fno-warn-incomplete-patterns #-}

module Main (main) where

import qualified Data.List as List
import System.Environment (getArgs)

nats :: [Int]
nats = [1..]

fibs :: [Int]
fibs = 0 : scanl (+) 1 fibs

fibs' :: [Int]
fibs' = 0 : List.scanl' (+) 1 fibs'

rev_knot :: [a] -> [a]
rev_knot xs0 = let (xs3, xs5) = go [] xs3 xs0 in xs5 where
    go xs2 ~[]       []       = (xs2, [])
    go xs2 ~(x4:xs4) (x1:xs1) =
        let (xs3, xs5) = go (x1:xs2) xs4 xs1
        in (xs3, x4:xs5)
{-# INLINE rev_knot #-}

rev_forw :: [a] -> [a]
rev_forw xs0 = foldr (\_ k ~(x:xs) -> x : k xs) (\_ -> []) xs0 (reverse xs0)
{-# INLINE rev_forw #-}

rev_back :: [a] -> [a]
rev_back xs0 = snd $ foldr (\_ ~(~(x:xs1), xs2) -> (xs1, x:xs2)) (xs0, []) xs0
{-# INLINE rev_back #-}

main :: IO ()
main = do
  [producerName, limitName, consumerName, listName] <- getArgs
  let n = 1000000
      (pre, post) = case limitName of
          "before" -> (take n, id)
          "after" -> (id, take n)
      consumer = case consumerName of
          "sum" -> sum
          "length" -> length
      producer = case producerName of
          "reverse"      -> reverse
          "rev_knot"     -> rev_knot
          "rev_forw"     -> rev_forw
          "rev_back"     -> rev_back
      list = case listName of
          "nats"  -> nats
          "fibs"  -> fibs
          "fibs'" -> fibs'
  print . consumer . post . producer $ pre list
