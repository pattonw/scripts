from __future__ import with_statement
from org.scijava.vecmath import Vector3f
from mpicbg.models import Point, PointMatch
from net.imglib2 import KDTree, RealPoint
from net.imglib2.neighborsearch import RadiusNeighborSearchOnKDTree
from itertools import imap, izip, product
from jarray import array
import os, sys, csv
from os.path import basename
# local lib functions:
from dogpeaks import getDoGPeaks
from util import syncPrint, Task, Getter

# A custom feature, comparable with other features of the same kind
class Constellation:
  """ Expects 3 scalars and an iterable of scalars. """
  def __init__(self, angle, len1, len2, coords):
    self.angle = angle
    self.len1 = len1
    self.len2 = len2
    self.position = Point(array(coords, 'd'))

  def matches(self, other, angle_epsilon, len_epsilon_sq):
    """ Compare the angles, if less than epsilon, compare the vector lengths.
       Return True when deemed similar within measurement error brackets. """
    return abs(self.angle - other.angle) < angle_epsilon \
       and abs(self.len1 - other.len1) + abs(self.len2 - other.len2) < len_epsilon_sq

  @staticmethod
  def subtract(loc1, loc2):
    return (loc1.getFloatPosition(d) - loc2.getFloatPosition(d)
            for d in xrange(loc1.numDimensions()))

  @staticmethod
  def fromSearch(center, p1, d1, p2, d2):
    """ center, p1, p2 are 3 RealLocalizable, with center being the peak
        and p1, p2 being the wings (the other two points).
        p1 is always closer to center than p2 (d1 < d2).
        d1, d2 are the square distances from center to p1, p2
        (could be computed here, but RadiusNeighborSearchOnKDTree did it). """
    pos = tuple(center.getFloatPosition(d) for d in xrange(center.numDimensions()))
    v1 = Vector3f(Constellation.subtract(p1, center))
    v2 = Vector3f(Constellation.subtract(p2, center))
    return Constellation(v1.angle(v2), d1, d2, pos)

  @staticmethod
  def fromRow(row):
    """ Expects: row = [angle, len1, len2, x, y, z] """
    return Constellation(row[0], row[1], row[2], row[3:])

  def asRow(self):
    "Returns: [angle, len1, len2, position.x, position,y, position.z"
    return (self.angle, self.len1, self.len2) + tuple(self.position.getW())

  @staticmethod
  def csvHeader():
    return ["angle", "len1", "len2", "x", "y", "z"]


def makeRadiusSearch(peaks):
  """ Construct a KDTree-based radius search, for locating points
      within a given radius of a reference point. """
  return RadiusNeighborSearchOnKDTree(KDTree(peaks, peaks))


def extractFeatures(peaks, search, radius, min_angle, max_per_peak):
  """ Construct up to max_per_peak constellation features with furthest peaks. """
  constellations = []
  for peak in peaks:
    search.search(peak, radius, True) # sorted
    n = search.numNeighbors()
    if n > 2:
      yielded = 0
      # 0 is itself: skip from range of indices
      for i, j in izip(xrange(n -2, 0, -1), xrange(n -1, 0, -1)):
        if yielded == max_per_peak:
          break
        p1, d1 = search.getPosition(i), search.getSquareDistance(i)
        p2, d2 = search.getPosition(j), search.getSquareDistance(j)
        cons = Constellation.fromSearch(peak, p1, d1, p2, d2)
        if cons.angle >= min_angle:
          yielded += 1
          constellations.append(cons)
  #
  return constellations


class PointMatches():
  def __init__(self, pointmatches):
    self.pointmatches = pointmatches
  
  @staticmethod
  def fromFeatures(features1, features2, angle_epsilon, len_epsilon_sq):
    """ Compare all features of one image to all features of the other image,
        to identify matching features and then create PointMatch instances. """
    return PointMatches([PointMatch(c1.position, c2.position)
                         for c1, c2 in product(features1, features2)
                         if c1.matches(c2, angle_epsilon, len_epsilon_sq)])

  @staticmethod
  def fromNearbyFeatures(radius, features1, features2, angle_epsilon, len_epsilon_sq):
    """ Compare each feature in features1 to those features in features2
        that fall within the radius, using the search2 (a RadiusNeighborSearchOnKDTree). """
    # Construct log(n) search
    # (Uses RealPoint.wrap to avoid copying the double[] from getW())
    positions2 = [RealPoint.wrap(c2.position.getW()) for c2 in features2]
    search2 = RadiusNeighborSearchOnKDTree(KDTree(features2, positions2))
    pointmatches = []

    for c1 in features1:
      search2.search(RealPoint.wrap(c1.position.getW()), radius, False) # no need to sort
      pointmatches.extend(PointMatch(c1.position, c2.position)
                          for c2 in (search2.getSampler(i).get()
                                     for i in xrange(search2.numNeighbors()))
                          if c1.matches(c2, angle_epsilon, len_epsilon_sq))
    #
    return PointMatches(pointmatches)

  def toRows(self):
    return [tuple(p1.getW()) + tuple(p2.getW())
            for p1, p2 in self.pointmatches]

  @staticmethod
  def fromRows(rows):
    """ rows: from a CSV file, as lists of strings. """
    return PointMatches([PointMatch(Point(array(imap(float, row[0:3]), 'd')),
                                    Point(array(imap(float, row[3:6]), 'd')))
                         for row in rows])

  @staticmethod
  def csvHeader():
    return ["x1", "y1", "z1", "x2", "y2", "z2"]

  @staticmethod
  def asRow(pm):
    return tuple(pm.getP1().getW()) + tuple(pm.getP2().getW())


def saveFeatures(img_filename, directory, features, params):
  path = os.path.join(directory, basename(img_filename)) + ".features.csv"
  try:
    with open(path, 'w') as csvfile:
      w = csv.writer(csvfile, delimiter=',', quotechar='"', quoting=csv.QUOTE_NONNUMERIC)
      # First two rows: parameter names and values
      keys = params.keys()
      w.writerow(keys)
      w.writerow(tuple(params[key] for key in keys))
      # Feature header
      w.writerow(Constellation.csvHeader())
      # One row per Constellation feature
      for feature in features:
        w.writerow(feature.asRow())
      # Ensure it's written
      csvfile.flush()
      os.fsync(csvfile.fileno())
  except:
    syncPrint("Failed to save features at %s" % path)
    syncPrint(str(sys.exc_info()))


def loadFeatures(img_filename, directory, params, validateOnly=False, epsilon=0.00001):
  """ Attempts to load features from filename + ".features.csv" if it exists,
      returning a list of Constellation features or None.
      params: dictionary of parameters with which features are wanted now,
              to compare with parameter with which features were extracted.
              In case of mismatch, return None.
      epsilon: allowed error when comparing floating-point values.
      validateOnly: if True, return after checking that parameters match. """
  try:
    csvpath = os.path.join(directory, basename(img_filename) + ".features.csv")
    if os.path.exists(csvpath):
      with open(csvpath, 'r') as csvfile:
        reader = csv.reader(csvfile, delimiter=',', quotechar='"')
        # First line contains parameter names, second line their values
        paramsF = dict(izip(reader.next(), imap(float, reader.next())))
        for name in paramsF:
          if abs(params[name] - paramsF[name]) > 0.00001:
            syncPrint("Mismatching parameters: '%s' - %f != %f" % (name, params[name], paramsF[name]))
            return None
        if validateOnly:
          return True # would return None above, which is falsy
        reader.next() # skip header with column names
        features = [Constellation.fromRow(map(float, row)) for row in reader]
        syncPrint("Loaded %i features for %s" % (len(features), img_filename))
        return features
    else:
      syncPrint("No stored features found at %s" % csvpath)
      return None
  except:
    syncPrint("Could not load features for %s" % img_filename)
    syncPrint(str(sys.exc_info()))
    return None


def savePointMatches(img_filename1, img_filename2, pointmatches, directory, params):
  filename = basename(img_filename1) + '.' + basename(img_filename2) + ".pointmatches.csv"
  path = os.path.join(directory, filename)
  try:
    with open(path, 'w') as csvfile:
      w = csv.writer(csvfile, delimiter=',', quotechar='"', quoting=csv.QUOTE_NONNUMERIC)
      # First two rows: parameter names and values
      keys = params.keys()
      w.writerow(keys)
      w.writerow(tuple(params[key] for key in keys))
      # PointMatches header
      w.writerow(PointMatches.csvHeader())
      # One PointMatch per row
      for pm in pointmatches:
        w.writerow(PointMatches.asRow(pm))
      # Ensure it's written
      csvfile.flush()
      os.fsync(csvfile.fileno())
  except:
    syncPrint("Failed to save pointmatches at %s" % path)
    syncPrint(str(sys.exc_info()))
    


def loadPointMatches(img1_filename, img2_filename, directory, params, epsilon=0.00001):
  """ Attempts to load point matches from filename1 + '.' + filename2 + ".pointmatches.csv" if it exists,
      returning a list of PointMatch instances or None.
      params: dictionary of parameters with which pointmatches are wanted now,
              to compare with parameter with which pointmatches were made.
              In case of mismatch, return None.
      epsilon: allowed error when comparing floating-point values. """
  try:
    csvpath = os.path.join(directory, basename(img1_filename) + '.' + basename(img2_filename) + ".pointmatches.csv")
    if not os.path.exists(csvpath):
      syncPrint("No stored pointmatches found at %s" % csvpath)
      return None
    with open(csvpath, 'r') as csvfile:
      reader = csv.reader(csvfile, delimiter=',', quotechar='"')
      # First line contains parameter names, second line their values
      paramsF = dict(izip(reader.next(), imap(float, reader.next())))
      for name in paramsF:
        if abs(params[name] - paramsF[name]) > 0.00001:
          syncPrint("Mismatching parameters: '%s' - %f != %f" % (name, params[name], paramsF[name]))
          return None
      reader.next() # skip header with column names
      pointmatches = PointMatches.fromRows(reader).pointmatches
      syncPrint("Loaded %i pointmatches for %s, %s" % (len(pointmatches), img1_filename, img2_filename))
      return pointmatches
  except:
    syncPrint("Could not load pointmatches for pair %s, %s" % (img1_filename, img2_filename))
    syncPrint(str(sys.exc_info()))
    return None


def makeFeatures(img_filename, img_loader, getCalibration, csv_dir, params):
  """ Helper function to extract features from an image. """
  img = img_loader.load(img_filename)
  # Find a list of peaks by difference of Gaussian
  peaks = getDoGPeaks(img, getCalibration(img_filename),
                      params['sigmaSmaller'], params['sigmaLarger'],
                      params['minPeakValue'])
  if 0 == len(peaks):
    features = []
  else:
    # Create a KDTree-based search for nearby peaks
    search = makeRadiusSearch(peaks)
    # Create list of Constellation features
    features = extractFeatures(peaks, search,
                               params['radius'], params['min_angle'], params['max_per_peak'])
  if 0 == len(features):
    syncPrint("No peaks found for %s" % img_filename)
  # Store features in a CSV file (even if without features)
  saveFeatures(img_filename, csv_dir, features, params)
  return features


def findPointMatches(img1_filename, img2_filename, img_loader, getCalibration, csv_dir, exe, params):
  """ Attempt to load them from a CSV file, otherwise compute them and save them. """
  names = set(["minPeakValue", "sigmaSmaller", "sigmaLarger", # DoG peak params
               "radius", "min_angle", "max_per_peak",         # Constellation params
               "angle_epsilon", "len_epsilon_sq"])            # pointmatches params
  pm_params = {k: params[k] for k in names}
  # Attempt to load pointmatches from CSV file
  pointmatches = loadPointMatches(img1_filename, img2_filename, csv_dir, pm_params)
  if pointmatches is not None:
    return pointmatches

  # Load features from CSV files
  # otherwise compute them and save them.
  img_filenames = [img1_filename, img2_filename]
  names = set(["minPeakValue", "sigmaSmaller", "sigmaLarger",
                "radius", "min_angle", "max_per_peak"])
  feature_params = {k: params[k] for k in names}
  csv_features = [loadFeatures(img1_filename, csv_dir, feature_params)
                  for img_filename in img_filenames]
  # If features were loaded, just return them, otherwise compute them (and save them to CSV files)
  futures = [Getter(fs) if fs
             else exe.submit(Task(makeFeatures, img_filename, img_loader, getCalibration, csv_dir, feature_params))
             for fs, img_filename in izip(csv_features, img_filenames)]
  features = [f.get() for f in futures]
  
  for img_filename, fs in izip(img_filenames, features):
    syncPrint("Found %i constellation features in image %s" % (len(fs), img_filename))

  # Compare all possible pairs of constellation features: the PointMatches
  if params.get('pointmatches_nearby', False):
    # Use a RadiusNeighborSearchOnKDTree
    pm = PointMatches.fromNearbyFeatures(
        params['pointmatches_search_radius'],
        features[0], features[1],
        params["angle_epsilon"], params["len_epsilon_sq"])
  else:
    # All to all
    pm = PointMatches.fromFeatures(
        features[0], features[1],
        params["angle_epsilon"], params["len_epsilon_sq"])

  syncPrint("Found %i point matches between:\n    %s\n    %s" % \
            (len(pm.pointmatches), img1_filename, img2_filename))

  # Store as CSV file
  savePointMatches(img1_filename, img2_filename, pm.pointmatches, csv_dir, pm_params)
  #
  return pm.pointmatches


def ensureFeatures(img_filename, img_loader, getCalibration, csv_dir, params):
  names = set(["minPeakValue", "sigmaSmaller", "sigmaLarger",
               "radius", "min_angle", "max_per_peak"])
  feature_params = {k: params[k] for k in names}
  if not loadFeatures(img_filename, csv_dir, feature_params, validateOnly=True):
    # Create features from scratch, which overwrites any CSV files
    makeFeatures(img_filename, img_loader, getCalibration, csv_dir, feature_params)
    # TODO: Delete CSV files for pointmatches, if any

